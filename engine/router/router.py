"""Smart Image Router (P2): feature-based routing to content modules.

The router computes cheap image features (aspect ratio, edge density,
colorfulness, HMI colour ratio, flat-area ratio, text-pixel density from a
binarized Sobel response, quality flags) and combines them with the OCR
keyword cues into per-category scores. The highest score wins; ``unknown``
never wins by itself — a low best score routes to the general module with a
warning instead (the taxonomy's fallback rule).

Routing rules are registered as callables (``register_rule``) so P3+ modules
can add or override routing without touching this file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np

from engine.schema.taxonomy import Category, all_categories, get_category

# Saturated "HMI" colours: red / green / yellow / blue / orange used on
# industrial screens. Ratios are per-channel conditions on HSV.
HMI_KEYWORDS = (
    "alarm",
    "plc",
    "setpoint",
    "hmi",
    "scada",
    "temperature",
    "pressure",
    "rpm",
    "fault",
    "run",
    "stop",
    "auto",
    "manual",
    "recipe",
    "batch",
    # P4 (industrial module, additive): coil-table and label vocabulary
    "coil",
    "vòng",
    "lô",
    "trọng lượng",
    "bề rộng",
    "bề dày",
    "nameplate",
    "serial no",
)
DOCUMENT_KEYWORDS = (
    "invoice",
    "hóa đơn",
    "hóa",
    "đơn",
    "total",
    "tổng",
    "customer",
    "khách",
    "date",
    "ngày",
    "invoice no",
    "vat",
    "address",
    "địa chỉ",
)


@dataclass
class RouteFeatures:
    aspect_ratio: float  # width / height
    edge_density: float  # fraction of strong Sobel pixels
    colorfulness: float  # mean saturation of colored pixels
    hmi_color_ratio: float  # saturated red/green/yellow/blue pixel fraction
    flat_area_ratio: float  # near-uniform (quantized-level) pixel fraction
    text_pixel_density: float  # fraction of pixels in binarized text bands
    dominant_hue: float | None = None


@dataclass
class RouteDecision:
    category: Category
    confidence: float
    scores: dict[str, float] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    route_warning: str | None = None


# --- feature extraction ---------------------------------------------------


def extract_features(image: np.ndarray) -> RouteFeatures:
    img = image if image.ndim == 3 else np.stack([image] * 3, axis=-1)
    hsv = cvt_hsv(img)
    height, w = img.shape[:2]
    gray = np.ascontiguousarray(
        img.mean(axis=2) if img.shape[2] == 3 else img[:, :, 0], dtype=np.uint8
    )
    gx = np.abs(np.diff(gray.astype(np.float32), axis=1)).sum() / max(1, gray.size)
    gy = np.abs(np.diff(gray.astype(np.float32), axis=0)).sum() / max(1, gray.size)
    hue_ch, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    colored = s > 60
    colorfulness = float(s[colored].mean()) / 255.0 if colored.any() else 0.0
    hmi = _hmi_mask(hue_ch, s, v)
    flat = _flat_ratio(gray)
    text_density = _text_density(gray)
    hue = float(np.median(hue_ch[colored])) if colored.any() else None
    return RouteFeatures(
        aspect_ratio=w / max(1, height),
        edge_density=float(gx + gy),
        colorfulness=colorfulness,
        hmi_color_ratio=float(hmi.mean()),
        flat_area_ratio=flat,
        text_pixel_density=text_density,
        dominant_hue=hue,
    )


def cvt_hsv(img: np.ndarray) -> np.ndarray:
    if img.dtype != np.uint8:
        img = np.clip(img, 0, 255).astype(np.uint8)
    import cv2

    return cv2.cvtColor(img, cv2.COLOR_RGB2HSV)


def _sobel_fraction(gray: np.ndarray, thresh: float = 40.0) -> float:
    import cv2

    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1)
    mag = np.sqrt(gx * gx + gy * gy)
    return float((mag > thresh).mean())


def _hmi_mask(h: np.ndarray, s: np.ndarray, v: np.ndarray) -> np.ndarray:
    red = ((h < 12) | (h > 168)) & (s > 120) & (v > 60)
    green = (h >= 60) & (h <= 110) & (s > 120) & (v > 60)
    yellow = (h > 20) & (h < 40) & (s > 120) & (v > 120)
    blue = (h > 100) & (h < 135) & (s > 120) & (v > 60)
    return red | green | yellow | blue


def _flat_ratio(gray: np.ndarray, tol: int = 6) -> float:
    # fraction of pixels whose 5x5 neighbourhood variance is tiny
    import cv2

    mean = cv2.blur(gray.astype(np.float32), (5, 5))
    sq = cv2.blur((gray.astype(np.float32) - mean) ** 2, (5, 5))
    return float((sq < tol * tol).mean())


def _text_density(gray: np.ndarray) -> float:
    import cv2

    binary = cv2.adaptiveThreshold(
        gray.astype(np.uint8), 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 15, 10
    )
    return float(binary.mean() / 255.0)


def extract_keywords(text: str) -> list[str]:
    if not text:
        return []
    lowered = re.sub(r"\s+", " ", text.lower())
    return [kw for kw in set(HMI_KEYWORDS) | set(DOCUMENT_KEYWORDS) if kw in lowered]


# --- scoring ---------------------------------------------------------------


def _score_features(features: RouteFeatures) -> dict[str, float]:
    """Feature-only scores in [0, 1] per category id present in the registry."""
    scores: dict[str, float] = {}
    ids = set(all_categories())
    if "industrial_hmi" in ids:
        scores["industrial_hmi"] = min(
            1.0, 0.6 * min(1.0, features.hmi_color_ratio * 2) + 0.4 * features.flat_area_ratio
        )
    if "photo_document" in ids:
        scores["photo_document"] = min(
            1.0,
            0.6 * min(1.0, features.text_pixel_density * 3)
            + 0.4 * features.flat_area_ratio
            + 0.1 * (1.0 - features.colorfulness),
        )
    if "coil_table" in ids:
        scores["coil_table"] = 0.0  # P3+: table-structure cues
    if "handwritten_note" in ids:
        scores["handwritten_note"] = 0.0  # P5+: stroke-irregularity cues
    return scores


def route_image(
    image: np.ndarray,
    *,
    ocr_text: str = "",
    features: RouteFeatures | None = None,
) -> RouteDecision:
    """Route one processed image to a content category."""
    feats = features if features is not None else extract_features(image)
    scores = _score_features(feats)
    reasons: list[str] = []
    keywords = extract_keywords(ocr_text)
    if keywords:
        hmi_hits = [k for k in keywords if k in HMI_KEYWORDS]
        doc_hits = [k for k in keywords if k in DOCUMENT_KEYWORDS]
        if hmi_hits:
            scores["industrial_hmi"] = scores.get("industrial_hmi", 0.0) + 0.4
            reasons.append(f"HMI keywords: {sorted(set(hmi_hits))}")
        if doc_hits:
            scores["photo_document"] = scores.get("photo_document", 0.0) + 0.4
            reasons.append(f"document keywords: {sorted(set(doc_hits))[:4]}")

    known = {k: v for k, v in scores.items() if k != "unknown"}
    if not known:
        return RouteDecision(
            category=get_category("unknown"),
            confidence=0.0,
            scores=scores,
            reasons=["no registered category to score"],
            route_warning="no categories registered",
        )
    best_id = max(known, key=lambda k: known[k])
    best = known[best_id]
    try:
        category = get_category(best_id)
    except KeyError:  # defensive: registry changed under us
        category = get_category("unknown")
    warning = None
    if best < 0.3:
        category = get_category("unknown")
        warning = f"best category score {best:.2f} below 0.3; routed to unknown"
        reasons.append(warning)
    else:
        reasons.append(
            f"features: hmi_color={feats.hmi_color_ratio:.3f} "
            f"text_density={feats.text_pixel_density:.3f} "
            f"colorfulness={feats.colorfulness:.3f}"
        )
    return RouteDecision(
        category=category,
        confidence=min(1.0, best),
        scores=scores,
        reasons=reasons,
        keywords=sorted(set(keywords)),
        route_warning=warning,
    )


class SmartRouter:
    """Thin wrapper preserving a registry hook for module-specific rules."""

    def __init__(self) -> None:
        self._rules: list = []

    def register_rule(self, rule) -> None:
        """rule(features, ocr_text) -> RouteDecision | None; first hit wins."""
        self._rules.append(rule)

    def route(self, image: np.ndarray, *, ocr_text: str = "") -> RouteDecision:
        feats = extract_features(image)
        for rule in self._rules:
            decision = rule(feats, ocr_text)
            if decision is not None:
                return decision
        return route_image(image, ocr_text=ocr_text, features=feats)
