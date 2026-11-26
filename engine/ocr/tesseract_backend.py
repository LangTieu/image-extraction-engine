"""Tesseract backend via pytesseract (word-level tokens, TSV output)."""

from __future__ import annotations

import time

import numpy as np
import pytesseract

from engine.ocr.base import OCREngine, OCRResult, OCRToken, normalize_text


class TesseractEngine(OCREngine):
    name = "tesseract"

    def __init__(self, lang: str = "vie+eng", oem: int = 3, psm: int = 6) -> None:
        self._lang = lang
        self._oem = oem
        self._psm = psm

    @classmethod
    def from_options(cls, options) -> TesseractEngine:
        """Build from ``engine.options.OcrOptions``."""
        return cls(
            lang=options.tesseract_lang, oem=options.tesseract_oem, psm=options.tesseract_psm
        )

    def recognize(self, image, *, languages=("vi", "en"), min_confidence=0.0) -> OCRResult:
        t0 = time.perf_counter()
        arr = image if isinstance(image, np.ndarray) else np.asarray(image)
        data = pytesseract.image_to_data(
            arr,
            lang=self._lang,
            config=f"--oem {self._oem} --psm {self._psm}",
            output_type=pytesseract.Output.DICT,
        )
        tokens: list[OCRToken] = []
        for text, conf, x, y, w, h in zip(
            data["text"],
            data["conf"],
            data["left"],
            data["top"],
            data["width"],
            data["height"],
        ):
            text = normalize_text(str(text)).strip()
            if not text or int(conf) < 0:
                continue
            score = float(conf) / 100.0
            if score < min_confidence:
                continue
            tokens.append(
                OCRToken(
                    text=text,
                    bbox=(float(x), float(y), float(x + w), float(y + h)),
                    confidence=score,
                    language=self._lang.split("+")[0],
                )
            )
        return OCRResult(
            tokens=tokens, engine=self.name, elapsed_ms=(time.perf_counter() - t0) * 1000
        )
