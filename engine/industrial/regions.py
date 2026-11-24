"""Region detection on HMI screens (P4 item 3).

Segments a normalized screen into panels, tables, label/value boxes, alarm
banners and status indicators using contours plus HSV colour segmentation of
typical HMI palettes (alarm red/yellow, indicator green/blue). An optional
detector-model hook (interface only) may add proposal regions; no model is
downloaded.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum

import numpy as np

MIN_REGION_AREA_RATIO = 0.002


class RegionType(StrEnum):
    PANEL = "panel"
    TABLE = "table"
    LABEL_VALUE = "label_value"
    ALARM_BANNER = "alarm_banner"
    STATUS_INDICATOR = "status_indicator"


@dataclass
class Region:
    type: RegionType
    bbox: tuple[float, float, float, float]
    score: float
    color: str | None = None  # dominant saturated colour, if any
    source: str = "heuristic"  # or "model"

    @property
    def area(self) -> float:
        return (self.bbox[2] - self.bbox[0]) * (self.bbox[3] - self.bbox[1])


class DetectorModelHook(ABC):
    """Optional external region-detector hook (interface only, P4 item 3).

    Implementations return model-proposed regions in image pixel
    coordinates; the industrial pipeline treats them as *proposals* that
    still need OCR/pixel support before anything is accepted.
    """

    @property
    def available(self) -> bool:
        return False

    @abstractmethod
    def detect(self, image: np.ndarray) -> list[Region]:
        """Return proposed regions for ``image`` (RGB uint8)."""


class UnavailableDetectorHook(DetectorModelHook):
    """Stub used when no detector model is configured (never downloads)."""

    @property
    def available(self) -> bool:
        return False

    def detect(self, image: np.ndarray) -> list[Region]:
        return []


# HSV ranges (OpenCV hue 0-179) for the typical HMI palette.
_PALETTE: dict[str, tuple[np.ndarray, np.ndarray]] = {
    "red": (np.array([0, 110, 70]), np.array([10, 255, 255])),
    "red2": (np.array([170, 110, 70]), np.array([179, 255, 255])),
    "yellow": (np.array([20, 110, 70]), np.array([40, 255, 255])),
    "green": (np.array([45, 110, 70]), np.array([85, 255, 255])),
    "blue": (np.array([95, 110, 70]), np.array([130, 255, 255])),
}

_ALARM_COLORS = {"red", "red2", "yellow"}


def _color_masks(hsv: np.ndarray) -> dict[str, np.ndarray]:
    return {name: cv2_in_range(hsv, lo, hi) for name, (lo, hi) in _PALETTE.items()}


def cv2_in_range(hsv: np.ndarray, lo: np.ndarray, hi: np.ndarray) -> np.ndarray:
    import cv2

    return cv2.inRange(hsv, lo, hi) > 0


def detect_regions(
    image: np.ndarray,
    *,
    model_hook: DetectorModelHook | None = None,
) -> list[Region]:
    """Segment an HMI screen into typed regions (heuristic + optional model)."""
    import cv2

    height, width = image.shape[:2]
    hsv = cv2.cvtColor(image, cv2.COLOR_RGB2HSV)
    masks = _color_masks(hsv)
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)

    regions: list[Region] = []
    seen_alarm: list[tuple[float, float, float, float]] = []

    # 1. alarm banners and status indicators from saturated colour blobs
    for name, mask in masks.items():
        blob_mask = mask.astype(np.uint8) * np.uint8(255)
        blob_mask = np.asarray(
            cv2.morphologyEx(blob_mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8)),
            dtype=np.uint8,
        )
        contours, _ = cv2.findContours(blob_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            area = w * h
            if area < MIN_REGION_AREA_RATIO * width * height:
                continue
            bbox = (float(x), float(y), float(x + w), float(y + h))
            fill = cv2.contourArea(contour) / max(1.0, area)
            if name in _ALARM_COLORS and w > 1.5 * h and fill > 0.4:
                regions.append(
                    Region(RegionType.ALARM_BANNER, bbox, score=min(1.0, fill), color=name)
                )
                seen_alarm.append(bbox)
            elif fill > 0.55 and 0.3 < w / max(1, h) < 3.5:
                regions.append(
                    Region(RegionType.STATUS_INDICATOR, bbox, score=min(1.0, fill), color=name)
                )

    # 2. structural regions from edges: panels and tables
    edges = cv2.Canny(gray, 60, 160)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        area = w * h
        if area < 0.02 * width * height or area > 0.98 * width * height:
            continue
        bbox = (float(x), float(y), float(x + w), float(y + h))
        if _is_ruled_grid(edges, bbox):
            regions.append(Region(RegionType.TABLE, bbox, score=0.6, source="heuristic"))
        elif _is_table_like(bbox, contours, cv2.contourArea(contour)):
            regions.append(Region(RegionType.TABLE, bbox, score=0.6, source="heuristic"))
        elif any(_contains(a, bbox) for a in seen_alarm):
            continue  # inside an alarm banner already typed
        else:
            regions.append(Region(RegionType.PANEL, bbox, score=0.4, source="heuristic"))

    # label/value boxes: alternating text gaps inside panels are refined by the
    # parser; here we emit small mid-size panels as label_value candidates.
    for region in regions:
        if region.type is RegionType.PANEL and region.area < 0.12 * width * height:
            region.type = RegionType.LABEL_VALUE

    if model_hook is not None and model_hook.available:
        regions.extend(model_hook.detect(image))

    return _drop_nested(regions)


def _is_ruled_grid(edges: np.ndarray, bbox: tuple[float, float, float, float]) -> bool:
    """A ruled table grid: >= 2 long horizontal and >= 2 long vertical lines.

    Works for both dark-lines-on-light scans and bright-lines-on-dark HMI
    screens (the connected grid outline alone has a near-full contour fill,
    so the hollow-rectangle test alone never fires on it).
    """
    x0, y0, x1, y1 = (int(v) for v in bbox)
    w, h = x1 - x0, y1 - y0
    if h < 8 or w < 8:
        return False
    crop = edges[y0:y1, x0:x1]
    # Projection profiles: grid lines show up as rows/columns with heavy edge
    # coverage. (Morphological dilation merges the grid into one blob, which
    # cannot be counted.)
    row_profile = crop.mean(axis=1) / 255.0
    col_profile = crop.mean(axis=0) / 255.0
    hcount = _count_bands(row_profile > 0.35)
    vcount = _count_bands(col_profile > 0.35)
    return hcount >= 2 and vcount >= 2


def _count_bands(flags: np.ndarray) -> int:
    """Number of contiguous True bands in a 1-D boolean profile."""
    bands = 0
    prev = False
    for flag in flags:
        if flag and not prev:
            bands += 1
        prev = flag
    return bands


def _is_table_like(bbox: tuple[float, float, float, float], _contours, contour_area: float) -> bool:
    x0, y0, x1, y1 = bbox
    w, h = x1 - x0, y1 - y0
    if h < 8:
        return False
    return w / h > 1.2 and contour_area / max(1.0, w * h) < 0.6  # hollow rectangle


def _contains(
    outer: tuple[float, float, float, float], inner: tuple[float, float, float, float]
) -> bool:
    ox0, oy0, ox1, oy1 = outer
    ix0, iy0, ix1, iy1 = inner
    return ox0 <= ix0 and oy0 <= iy0 and ix1 <= ox1 and iy1 <= oy1


def _drop_nested(regions: list[Region]) -> list[Region]:
    kept: list[Region] = []
    for region in regions:
        nested = any(
            other is not region
            and other.type is not RegionType.STATUS_INDICATOR
            and _contains(other.bbox, region.bbox)
            and other.area > region.area * 1.2
            for other in regions
        )
        if not nested:
            kept.append(region)
    return kept
