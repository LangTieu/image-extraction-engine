"""Compact OCR for industrial strings (P4 item 4).

Short alphanumeric strings and digits are re-OCR'd from upscaled region
crops with per-field-type character whitelists (pytesseract). Seven-segment
/LCD-style digit fields are read with a segment-template classifier when
they look segmented. Confusable characters (0/O, 1/I/l, 5/S, 8/B) are never
silently guessed: every reading records top-k alternatives and a flag.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np

try:  # optional at import; the pipeline degrades with a flag when absent
    import pytesseract
except ImportError:  # pragma: no cover
    pytesseract = None

from engine.industrial.values import CONFUSABLE_ALTERNATIVES

# whitelist per field type
WHITELISTS: dict[str, str] = {
    "id": "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-",
    "string": "",
    "number": "0123456789.,-",
    "integer": "0123456789-",
}

_PSM_SINGLE_LINE = "--psm 7"
_PSM_SINGLE_WORD = "--psm 8"


@dataclass
class CompactReading:
    text: str
    confidence: float
    alternatives: list[str] = field(default_factory=list)  # top-k alternates for confusables
    flags: list[str] = field(default_factory=list)


def _upscale(crop: np.ndarray, factor: float = 4.0) -> np.ndarray:
    import cv2

    height, width = crop.shape[:2]
    if factor == 1.0 or height < 2 or width < 2:
        return crop
    return cv2.resize(
        crop, None, fx=factor, fy=factor, interpolation=cv2.INTER_CUBIC
    )


def _to_gray(crop: np.ndarray) -> np.ndarray:
    import cv2

    if crop.ndim == 2:
        return crop
    if crop.shape[2] == 1:  # single-channel HxWx1
        return crop[:, :, 0]
    return cv2.cvtColor(crop[..., :3], cv2.COLOR_RGB2GRAY)  # any multi-channel layout


def shallow_text(image: np.ndarray, *, upscale: float = 1.0) -> str:
    """Whole-frame OCR for profile matching, polarity-normalized.

    Unlike :func:`read_compact` this skips binarization (on full frames the
    table grid lines dominate it and tesseract returns rules instead of
    text) and only flips bright-on-dark HMI screens to dark-on-light.
    """
    import cv2

    if pytesseract is None or image.size == 0:
        return ""
    gray = _to_gray(image)
    norm = np.empty_like(gray)
    cv2.normalize(gray, norm, 0, 255, cv2.NORM_MINMAX)
    if norm.mean() < 127.5:  # dark HMI background -> invert for tesseract
        norm = cv2.bitwise_not(norm)
    upscaled = _upscale(norm, upscale)
    try:
        return pytesseract.image_to_string(upscaled)
    except Exception:  # tesseract missing or failed on this frame
        return ""


def _prep(crop: np.ndarray) -> np.ndarray:
    import cv2

    gray = _to_gray(crop)
    norm = np.empty_like(gray)
    cv2.normalize(gray, norm, 0, 255, cv2.NORM_MINMAX)
    gray = norm
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    # Bright-on-dark (HMI/LED) text binarizes to white text on a black
    # background; tesseract and the segment classifier expect dark ink on a
    # light background, so invert when the background came out dark.
    if binary.mean() < 127.5:
        binary = cv2.bitwise_not(binary)
    return binary


def read_compact(
    crop: np.ndarray,
    *,
    field_type: str = "string",
    seven_segment: bool = False,
    upscale: float = 4.0,
) -> CompactReading:
    """Read one short region with a type-specific whitelist."""
    flags: list[str] = []
    if crop.size == 0:
        return CompactReading("", 0.0, flags=["empty crop"])
    if seven_segment:
        seven = read_seven_segment(_prep(crop))
        if seven is not None:
            return seven
        flags.append("seven_segment_fallback_to_ocr")

    upscaled = _upscale(crop, upscale)
    binary = _prep(upscaled)
    whitelist = WHITELISTS.get(field_type, "")
    # Both branches deliberately use PSM 7 (single text line): PSM 8 (single
    # word) was tried for whitelisted numeric fields and split/merged digit
    # groups on machine-printed strings, lowering accuracy. Kept as a flat
    # assignment so the ternary doesn't suggest a real difference.
    config = _PSM_SINGLE_LINE if whitelist else _PSM_SINGLE_LINE
    if whitelist:
        config += f" -c tessedit_char_whitelist={whitelist}"
    if pytesseract is None:
        flags.append("pytesseract_unavailable")
        return CompactReading("", 0.0, flags=flags)
    try:
        data = pytesseract.image_to_data(
            binary, config=config, output_type=pytesseract.Output.DICT
        )
    except Exception as error:  # tesseract missing or failed on this crop
        return CompactReading("", 0.0, flags=[f"ocr_error: {error}"])
    words = [
        (str(data["text"][i]).strip(), float(data["conf"][i]))
        for i in range(len(data["text"]))
        if str(data["text"][i]).strip() and float(data["conf"][i]) >= 0
    ]
    if not words:
        return CompactReading("", 0.0, flags=["no_text"])
    text = "".join(w for w, _ in words)
    confidence = sum(c for _, c in words) / len(words) / 100.0
    alternatives = _alternatives(text)
    if alternatives:
        flags.append("confusable_characters")
    if confidence < 0.75:
        flags.append("low_confidence")
    return CompactReading(text, confidence, alternatives=alternatives, flags=flags)


def _alternatives(text: str) -> list[str]:
    """Top-k alternates for confusable characters; empty when unambiguous."""
    hits = [(i, ch) for i, ch in enumerate(text) if ch in CONFUSABLE_ALTERNATIVES]
    if not hits:
        return []
    out = [text]
    # whole-class swaps first: every O -> 0 etc., the common OCR systematic mix
    for ch in dict.fromkeys(ch for _, ch in hits):
        for alt in CONFUSABLE_ALTERNATIVES[ch]:
            candidate = text.replace(ch, alt)
            if candidate not in out:
                out.append(candidate)
    for i, ch in hits[:3]:
        for v in list(out):
            for alt in CONFUSABLE_ALTERNATIVES[ch]:
                candidate = v[:i] + alt + v[i + 1 :]
                if candidate not in out:
                    out.append(candidate)
    return out[1:6]


# --- seven-segment ---------------------------------------------------------

# segment layout: a top, b top-right, c bottom-right, d bottom, e bottom-left,
# f top-left, g middle. Bitmask per digit.
_SEGMENTS: dict[int, str] = {
    0b1111110: "0",
    0b0110000: "1",
    0b1101101: "2",
    0b1111001: "3",
    0b0110011: "4",
    0b1011011: "5",
    0b1011111: "6",
    0b1110000: "7",
    0b1111111: "8",
    0b1111011: "9",
}


def read_seven_segment(binary: np.ndarray) -> CompactReading | None:
    """Classify one seven-segment glyph from a binarized crop (ink = on)."""
    import cv2

    contours, _ = cv2.findContours(
        (binary < 255).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    if not contours:
        return None
    x, y, w, h = cv2.boundingRect(max(contours, key=cv2.contourArea))
    if h < 6:
        return None
    glyph = (binary < 255)[y : y + h, x : x + w]
    filled = glyph.mean()
    if not (0.05 < filled < 0.55):  # LCD glyphs are mostly background
        return None

    def seg(x0f: float, x1f: float, y0f: float, y1f: float) -> bool:
        y0, y1 = int(y0f * h), int(y1f * h)
        x0, x1 = int(x0f * w), int(x1f * w)
        return bool(glyph[y0:y1, x0:x1].mean() > 0.45)

    code = (
        seg(0.2, 0.8, 0.0, 0.2) << 6
        | seg(0.8, 1.0, 0.1, 0.45) << 5
        | seg(0.8, 1.0, 0.55, 0.9) << 4
        | seg(0.2, 0.8, 0.8, 1.0) << 3
        | seg(0.0, 0.2, 0.55, 0.9) << 2
        | seg(0.0, 0.2, 0.1, 0.45) << 1
        | seg(0.2, 0.8, 0.42, 0.58)
    )
    digit = _SEGMENTS.get(code)
    if digit is None:
        return None
    # multi-digit strings: apply per glyph via horizontal slicing by caller is
    # out of scope; single-glyph reads are the common LCD case here.
    return CompactReading(digit, 0.9, flags=["seven_segment"])


def is_id_like(text: str, pattern: str | None = None) -> bool:
    if pattern:
        return re.fullmatch(pattern, text) is not None
    return bool(re.fullmatch(r"[A-Z0-9\-]{4,}", text))
