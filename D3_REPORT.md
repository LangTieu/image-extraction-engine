# D3 Report — OCR/preprocess options

Branch `d3-options`, commit `68450d6`. Base: main at `599c4ca`.

## What was built

- `engine/options.py` — two dataclasses in the `ExportOptions` style:
  - `PreprocessOptions(profile="industrial_screen_photo", overrides={}, dpi=300)` —
    bunded-profile name, per-step overrides (worker semantics: they *replace* the
    profile's steps via `from_dict`), PDF rasterization DPI. `__post_init__`
    validates dpi in [72, 600] and rejects an empty profile name.
  - `OcrOptions(engine="tesseract", tesseract_lang="vie+eng", tesseract_oem=3,
    tesseract_psm=6, paddle_lang="vi", paddle_enable_mkldnn=False,
    low_confidence=0.6, pdf_dpi=200)` — every constructor argument of
    `TesseractEngine` and `PaddleOCREngine` plus the `GeneralOCR` knobs.
    Validates psm [0, 13], oem [0, 3], low_confidence [0, 1], pdf_dpi [72, 600].
- `from_options` constructors added:
  - `PreprocessingPipeline.from_options(PreprocessOptions)`
  - `TesseractEngine.from_options(OcrOptions)`
  - `PaddleOCREngine.from_options(OcrOptions)` — stores `enable_mkldnn`
    (default stays `False`: oneDNN PIR conversion crashes on this CPU family)
  - `GeneralOCR.from_options(engines, OcrOptions)`
- `service/worker/runner.py` now builds everything from the options objects,
  including the previously hardcoded `GeneralOCR` defaults (`low_confidence=0.6`,
  `pdf_dpi=200`) and per-job `dpi` / `pdf_dpi` / `languages` job options.
  Defaults match the old behavior exactly.

## Gates (all run in this task)

| Gate | Result |
| --- | --- |
| `pytest tests/ -q` | 198 passed (same as baseline on `main`) |
| `python -m benchmark.validate benchmark/seed` | 35 passed, 0 failed |
| `ruff check .` | All checks passed |
| `mypy engine benchmark tests` | Success: no issues in 91 source files |

Live smoke: `PreprocessOptions → PreprocessingPipeline.from_options →
IndustrialVision(preprocessing, GeneralOCR.from_options([TesseractEngine.from_options(...)]))`
constructs end-to-end. Secret scan on the changed files: clean.

## Blocked / open

- `tests/test_options.py` (required by the brief) could not be created: the
  session's approval gate rejected new test files twice. Per the brief's
  test-file guard, the complete file is below; **the liaison must place it at
  `tests/test_options.py`** and run it (it targets the committed code).

```python
"""Tests for engine.options (D3): defaults, validation, from_options wiring.

Requested by mlai_d3_brief.md (D3 deliverable); placed by the liaison per the
brief's test-file guard.
"""

from __future__ import annotations

import pytest

from engine.options import OcrOptions, PreprocessOptions
from engine.ocr.paddle_backend import PaddleOCREngine
from engine.ocr.pipeline import GeneralOCR
from engine.ocr.tesseract_backend import TesseractEngine
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
```

## Fix round 3 (2026-11-26): null job options crash default uploads

Liaison-found: a default upload (no query params) stored `{"languages": null,
...}` in job options; the worker passed `None` through to
`TesseractEngine`, whose OCR call crashed with
`AttributeError: 'NoneType' object has no attribute 'split'`
(`tesseract_backend.py:57`, `self._lang.split("+")`) — job
`job_5fe627eacdb4` in the liaison's session.

Changes:

- `service/worker/runner.py`: new `build_engine_options(options, profile)`
  helper maps job options to `PreprocessOptions`/`OcrOptions`, treating an
  explicit `null` exactly like a missing key (all four knobs: `dpi`,
  `pdf_dpi`, `languages`, `preprocessing`); `_process_file` uses it. Also
  configures root logging (INFO) when the embedding app has none, so the
  effective-options INFO line actually emits.
- `engine/options.py`: `__post_init__` guards reject `None`/empty
  `tesseract_lang` and `paddle_lang` with a clear `ValueError` (defense in
  depth if a future caller bypasses the worker mapping).
- `tests/test_options.py`: +7 tests (5 parametrized null-cases, explicit
  values still win, None langs rejected).

Verification (all run in this task):

| Gate | Result |
| --- | --- |
| `pytest tests/ -q -p no:warnings` | 221 passed (baseline 214) |
| `python -m benchmark.validate` | 35 passed, 0 failed |
| `ruff check` (touched files) | All checks passed |
| `mypy engine/options.py service/worker/runner.py` | Success |

Live smoke on `uvicorn service.api.app:app` (port 3000): the brief's failing
upload (`POST /v1/jobs`, no query params, PNG in
`benchmark/seed/photo_document/images/`) now completes — job
`job_eb311f82016c`, status `completed`. Result key sets identical before vs
after fix (top level and per-file and extraction objects). Pre-fix crash
reproduced on stashed HEAD code with rendered text:
`AttributeError: 'NoneType' object has no attribute 'split'`; fixed code
raises the clear `ValueError` instead. Effective-options INFO line confirmed
in the server log. Secret scan on the diff: clean.

