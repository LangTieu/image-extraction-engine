"""Collected engine options (D3).

One place for the knobs the application layer may set, so callers never
need to know engine-internal parameter names. Defaults match today's
behavior exactly (worker used ``TesseractEngine()`` /
``GeneralOCR([ocr_engine])`` / ``load_input(path)``).

Style follows ``engine/export/base.py:ExportOptions``: a dataclass with
documented defaults and ``__post_init__`` validation.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

from engine.preprocessing.io import DEFAULT_DPI
from engine.preprocessing.pipeline import PreprocessingPipeline

MIN_DPI = 72
MAX_DPI = 600


@dataclass(frozen=True)
class PreprocessOptions:
    """Preprocessing knobs: which profile, per-step overrides, raster DPI."""

    # Bundled profile name (engine/preprocessing/profiles/*.yaml).
    profile: str = "industrial_screen_photo"
    # Per-step overrides, applied exactly like from_dict steps: keys are
    # step names (PROFILE_ORDER), values are that step's config kwargs.
    # They REPLACE the profile's steps for the pipeline (today's worker
    # semantics), they are not merged into it.
    overrides: Mapping[str, Mapping[str, object]] = field(default_factory=dict)
    # DPI used to rasterize PDF inputs (engine/preprocessing/io.py).
    dpi: int = DEFAULT_DPI

    def __post_init__(self) -> None:
        if not (MIN_DPI <= self.dpi <= MAX_DPI):
            raise ValueError(f"dpi must be in [{MIN_DPI}, {MAX_DPI}], got {self.dpi}")
        if not self.profile:
            raise ValueError("profile must be a non-empty name")
        try:
            PreprocessingPipeline.for_profile(self.profile)
        except FileNotFoundError:
            raise ValueError(f"unknown preprocessing profile: {self.profile!r}") from None


@dataclass(frozen=True)
class OcrOptions:
    """OCR knobs: which backend and every constructor argument it takes."""

    engine: Literal["tesseract", "paddle"] = "tesseract"
    # Tesseract (engine/ocr/tesseract_backend.py defaults).
    tesseract_lang: str = "vie+eng"
    tesseract_oem: int = 3  # OEM: 0=legacy, 1=LSTM, 2=combined, 3=default
    tesseract_psm: int = 6  # PSM 0-13: page segmentation mode
    # Paddle (engine/ocr/paddle_backend.py defaults; mkldnn off: PaddlePaddle
    # 3.x crashes on oneDNN PIR conversion on this CPU family).
    paddle_lang: str = "vi"
    paddle_enable_mkldnn: bool = False
    # Orchestration (engine/ocr/pipeline.py:GeneralOCR defaults).
    low_confidence: float = 0.6  # token re-OCR threshold, [0, 1]
    pdf_dpi: int = 200  # rasterization DPI for the PDF fast path

    def __post_init__(self) -> None:
        if not (0 <= self.tesseract_psm <= 13):
            raise ValueError(f"tesseract_psm must be in [0, 13], got {self.tesseract_psm}")
        if not (0 <= self.tesseract_oem <= 3):
            raise ValueError(f"tesseract_oem must be in [0, 3], got {self.tesseract_oem}")
        if not (0.0 <= self.low_confidence <= 1.0):
            raise ValueError(f"low_confidence must be in [0, 1], got {self.low_confidence}")
        if not (MIN_DPI <= self.pdf_dpi <= MAX_DPI):
            raise ValueError(f"pdf_dpi must be in [{MIN_DPI}, {MAX_DPI}], got {self.pdf_dpi}")
