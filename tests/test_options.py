"""Tests for engine.options (D3): defaults, validation, from_options wiring.

Requested by mlai_d3_brief.md (D3 deliverable); placed by the liaison per the
brief's test-file guard.
"""

from __future__ import annotations

import pytest

from engine.ocr.paddle_backend import PaddleOCREngine
from engine.ocr.pipeline import GeneralOCR
from engine.ocr.tesseract_backend import TesseractEngine
from engine.options import OcrOptions, PreprocessOptions
from engine.preprocessing.pipeline import PreprocessingPipeline


def test_preprocess_defaults_match_worker() -> None:
    options = PreprocessOptions()
    assert options.profile == "industrial_screen_photo"
    assert options.dpi == 300
    assert options.overrides == {}


def test_ocr_defaults_match_worker() -> None:
    options = OcrOptions()
    assert options.engine == "tesseract"
    assert options.tesseract_lang == "vie+eng"
    assert options.tesseract_oem == 3
    assert options.tesseract_psm == 6
    assert options.pdf_dpi == 200
    assert options.low_confidence == 0.6
    assert options.paddle_lang == "vi"
    assert options.paddle_enable_mkldnn is False


def test_preprocess_rejects_unknown_profile() -> None:
    with pytest.raises(ValueError, match="unknown preprocessing profile"):
        PreprocessOptions(profile="nope")


@pytest.mark.parametrize("dpi", [0, 71, 601, -300])
def test_preprocess_rejects_bad_dpi(dpi: int) -> None:
    with pytest.raises(ValueError, match="dpi"):
        PreprocessOptions(dpi=dpi)


def test_preprocess_accepts_dpi_boundaries() -> None:
    assert PreprocessOptions(dpi=72).dpi == 72
    assert PreprocessOptions(dpi=600).dpi == 600


def test_ocr_psm_range() -> None:
    OcrOptions(tesseract_psm=0)
    OcrOptions(tesseract_psm=13)
    with pytest.raises(ValueError, match="tesseract_psm"):
        OcrOptions(tesseract_psm=99)
    with pytest.raises(ValueError, match="tesseract_psm"):
        OcrOptions(tesseract_psm=-1)


def test_ocr_oem_range() -> None:
    OcrOptions(tesseract_oem=3)
    with pytest.raises(ValueError, match="tesseract_oem"):
        OcrOptions(tesseract_oem=4)


def test_ocr_low_confidence_range() -> None:
    OcrOptions(low_confidence=0.0)
    OcrOptions(low_confidence=1.0)
    with pytest.raises(ValueError, match="low_confidence"):
        OcrOptions(low_confidence=1.5)


def test_ocr_pdf_dpi_range() -> None:
    with pytest.raises(ValueError, match="pdf_dpi"):
        OcrOptions(pdf_dpi=50)
    with pytest.raises(ValueError, match="pdf_dpi"):
        OcrOptions(pdf_dpi=1000)


def test_preprocessing_pipeline_from_options_applies_overrides_like_from_dict() -> None:
    options = PreprocessOptions(overrides={"contrast": {"clip_limit": 4.0}, "sharpen": {}})
    pipeline = PreprocessingPipeline.from_options(options)
    via_dict = PreprocessingPipeline.from_dict(
        "industrial_screen_photo", {"contrast": {"clip_limit": 4.0}, "sharpen": {}}
    )
    assert pipeline.profile_name == via_dict.profile_name
    assert pipeline.steps == via_dict.steps == {"contrast": {"clip_limit": 4.0}, "sharpen": {}}


def test_tesseract_from_options() -> None:
    engine = TesseractEngine.from_options(
        OcrOptions(tesseract_lang="en", tesseract_oem=1, tesseract_psm=11)
    )
    assert engine._lang == "en"
    assert engine._oem == 1
    assert engine._psm == 11


def test_paddle_from_options_mkldnn_flag() -> None:
    engine = PaddleOCREngine.from_options(OcrOptions(paddle_lang="en"))
    assert engine._lang == "en"
    # Default stays off (oneDNN PIR conversion crashes on this CPU family).
    assert engine._enable_mkldnn is False
    custom = PaddleOCREngine.from_options(OcrOptions(paddle_enable_mkldnn=True))
    assert custom._enable_mkldnn is True


def test_general_ocr_from_options() -> None:
    ocr = GeneralOCR.from_options([TesseractEngine()], OcrOptions())
    assert ocr.low_confidence == 0.6
    assert ocr.dpi == 200
    custom = GeneralOCR.from_options(
        [TesseractEngine()], OcrOptions(low_confidence=0.9, pdf_dpi=150)
    )
    assert custom.low_confidence == 0.9
    assert custom.dpi == 150


# --- D3 fix: explicit nulls in stored job options must not crash the worker ---

NULL_JOBS = [
    {"dpi": None},
    {"pdf_dpi": None},
    {"languages": None},
    {"preprocessing": None},
    {"dpi": None, "pdf_dpi": None, "languages": None, "preprocessing": None},
]


@pytest.mark.parametrize("job_options", NULL_JOBS)
def test_build_engine_options_null_means_default(job_options: dict) -> None:
    from service.worker.runner import build_engine_options

    preprocess, ocr = build_engine_options(job_options, "industrial_screen_photo")
    default_preprocess, default_ocr = build_engine_options({}, "industrial_screen_photo")
    assert preprocess == default_preprocess
    assert ocr == default_ocr


def test_build_engine_options_explicit_values_win_over_nulls() -> None:
    from service.worker.runner import build_engine_options

    preprocess, ocr = build_engine_options(
        {"dpi": 400, "pdf_dpi": 150, "languages": "en", "preprocessing": {"sharpen": {}}},
        "industrial_screen_photo",
    )
    assert preprocess.dpi == 400
    assert preprocess.overrides == {"sharpen": {}}
    assert ocr.tesseract_lang == "en"
    assert ocr.pdf_dpi == 150


def test_ocr_options_reject_none_langs() -> None:
    with pytest.raises(ValueError, match="tesseract_lang"):
        OcrOptions(tesseract_lang=None)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="paddle_lang"):
        OcrOptions(paddle_lang=None)  # type: ignore[arg-type]
