"""OCR backend abstraction (P2).

An OCREngine turns one RGB uint8 image into a list of OCRToken: word- or
line-level text with an axis-aligned pixel bbox in *that image's*
coordinates, a confidence in [0, 1] and a detected BCP-47 language hint.
Backends never see the rest of the pipeline; the orchestrator is responsible
for ROI cropping, scaling and coordinate mapping back to the original image.
"""

from __future__ import annotations

import time
import unicodedata
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


def normalize_text(text: str) -> str:
    """Unicode NFC normalization so Vietnamese diacritics compare equal."""
    return unicodedata.normalize("NFC", text)


@dataclass
class OCRToken:
    """One recognized text unit (usually a word or a text line)."""

    text: str
    bbox: tuple[float, float, float, float]  # x0, y0, x1, y1 in px
    confidence: float
    language: str | None = None
    bbox_original: tuple[float, float, float, float] | None = None
    """Same box mapped back to the original image (set by the orchestrator)."""
    page_index: int | None = None
    """0-based page number (PDF paths; None for single images)."""
    scale: float | None = None
    """Render factor (DPI / 72) between PDF page points and raster pixels."""


@dataclass
class OCRResult:
    tokens: list[OCRToken] = field(default_factory=list)
    engine: str = ""
    elapsed_ms: float = 0.0


class OCREngine(ABC):
    """Abstract OCR backend. Implementations must be lazy: heavy model
    initialization happens on first recognize() call, not on construction."""

    name: str = "ocr"

    @abstractmethod
    def recognize(
        self,
        image: object,
        *,
        languages: tuple[str, ...] = ("vi", "en"),
        min_confidence: float = 0.0,
    ) -> OCRResult: ...

    def _timed(self, tokens: list[OCRToken], t0: float) -> OCRResult:
        return OCRResult(
            tokens=tokens, engine=self.name, elapsed_ms=(time.perf_counter() - t0) * 1000
        )
