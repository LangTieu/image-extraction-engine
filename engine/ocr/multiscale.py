"""Multi-scale re-OCR: retry low-confidence regions at higher resolution."""

from __future__ import annotations

import cv2
import numpy as np

from engine.ocr.base import OCREngine, OCRResult, OCRToken


def reocr_low_confidence(
    image: np.ndarray,
    result: OCRResult,
    engine: OCREngine,
    *,
    threshold: float = 0.6,
    scale: int = 2,
    min_roi_size: int = 8,
    max_retries: int = 48,
) -> OCRResult:
    """Re-recognize every token below ``threshold`` from a 2x crop.

    The crop is taken with padding around the token bbox, OCR runs on the
    upscaled crop, and the best-scoring result (by mean confidence) replaces
    the original token's text, confidence and bbox (scaled back).

    At most ``max_retries`` tokens are retried per call, lowest-confidence
    first. Real photos of screens (glare, moiré) can mark hundreds of tokens
    low-confidence; retrying each one took minutes of wall time while the
    retries on unreadable glare crops almost never improved the text.
    """
    if not result.tokens:
        return result
    h, w = image.shape[:2]
    low = sorted(
        (t for t in result.tokens if t.confidence < threshold),
        key=lambda t: t.confidence,
    )
    retry_set = {id(t) for t in low[:max_retries]}
    kept: list[OCRToken] = []
    for token in result.tokens:
        if token.confidence >= threshold or id(token) not in retry_set:
            kept.append(token)
            continue

        x0, y0, x1, y1 = token.bbox
        pad_x = max(4, (x1 - x0) * 0.5)
        pad_y = max(4, (y1 - y0) * 0.5)
        cx0 = int(max(0, x0 - pad_x))
        cy0 = int(max(0, y0 - pad_y))
        cx1 = int(min(w, x1 + pad_x))
        cy1 = int(min(h, y1 + pad_y))
        if cx1 - cx0 < min_roi_size or cy1 - cy0 < min_roi_size:
            kept.append(token)
            continue
        crop = image[cy0:cy1, cx0:cx1]
        crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        try:
            retry_result = engine.recognize(crop)
        except Exception:  # backend failure: keep the original token
            kept.append(token)
            continue
        retry_tokens = [t for t in retry_result.tokens if t.confidence >= threshold]
        if retry_tokens:
            best = max(retry_tokens, key=lambda t: t.confidence)
            # The retry only substitutes when it is genuinely better AND
            # spatially consistent with the original token: a small crop of a
            # padded ROI can return a neighbour's text at a different spot.
            x0, y0, x1, y1 = token.bbox
            area = max(1.0, (x1 - x0) * (y1 - y0))
            if best.confidence <= token.confidence:
                kept.append(token)
                continue
            bw = best.bbox[2] - best.bbox[0]
            bh = best.bbox[3] - best.bbox[1]
            # Map the crop-local bbox back to full-image coordinates. Only the
            # token's own extent is mapped (crop padding makes absolute
            # placement of the retry box unreliable beyond that).
            cx = cx0 + (best.bbox[0] + best.bbox[2]) / 2 / scale
            cy = cy0 + (best.bbox[1] + best.bbox[3]) / 2 / scale
            if bw > 0 and bh > 0:
                nb = (
                    cx - bw / 2 / scale,
                    cy - bh / 2 / scale,
                    cx + bw / 2 / scale,
                    cy + bh / 2 / scale,
                )
            else:
                nb = token.bbox
            # The retry crop is padded ~1.5x the token extent, so a mapped
            # box much larger than the original is a wrong pick (it swallowed
            # neighbouring text) — keep the original instead.
            if (nb[2] - nb[0]) * (nb[3] - nb[1]) > 2.25 * area:
                kept.append(token)
                continue
            kept.append(
                OCRToken(
                    text=best.text, bbox=nb, confidence=best.confidence, language=token.language
                )
            )
        else:
            kept.append(token)
    return OCRResult(tokens=kept, engine=result.engine, elapsed_ms=result.elapsed_ms)
