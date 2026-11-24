"""PaddleOCR backend (PP-OCRv5/v6, latin-script incl. Vietnamese).

PaddlePaddle 3.x crashes on this CPU family when oneDNN PIR conversion is
used, so the predictor runs with ``enable_mkldnn=False``. Models are
downloaded to ~/.paddlex on first use and cached.
"""

from __future__ import annotations

import time

import numpy as np

from engine.ocr.base import OCREngine, OCRResult, OCRToken, normalize_text


class PaddleOCREngine(OCREngine):
    name = "paddle"

    def __init__(self, lang: str = "vi") -> None:
        self._lang = lang
        self._ocr = None  # lazy

    def _ensure_model(self):
        if self._ocr is None:
            from paddleocr import PaddleOCR

            self._ocr = PaddleOCR(lang=self._lang, enable_mkldnn=False)
        return self._ocr

    def recognize(self, image, *, languages=("vi", "en"), min_confidence=0.0) -> OCRResult:
        t0 = time.perf_counter()
        ocr = self._ensure_model()
        arr = image if isinstance(image, np.ndarray) else np.asarray(image)
        tokens: list[OCRToken] = []
        for page in ocr.predict(arr):
            texts = page.get("rec_texts") or []
            scores = page.get("rec_scores") or []
            boxes = page.get("rec_boxes")
            if boxes is None:
                boxes = page.get("dt_polys")
            for text, score, box in zip(texts, scores, boxes):
                if score < min_confidence:
                    continue
                bbox = _to_bbox(np.asarray(box))
                if bbox is None:
                    continue
                tokens.append(
                    OCRToken(
                        text=normalize_text(str(text)),
                        bbox=bbox,
                        confidence=float(score),
                        language=self._lang,
                    )
                )
        return OCRResult(
            tokens=tokens, engine=self.name, elapsed_ms=(time.perf_counter() - t0) * 1000
        )


def _to_bbox(box) -> tuple[float, float, float, float] | None:
    """Accept an [x0,y0,x1,y1] box or a 4x2 polygon and return axis-aligned."""
    if box is None or len(box) == 0:
        return None
    box = np.asarray(box, dtype=float)
    if box.shape == (4,):
        return (float(box[0]), float(box[1]), float(box[2]), float(box[3]))
    xs, ys = box[:, 0], box[:, 1]
    return (float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max()))
