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
  session's approval gate rejected new test files twice. The brief's test-file
  deliverable is therefore NOT done; behavior is covered only by the existing
  suite plus the live smoke above. Approve creating `tests/test_options.py`
  and the tests from the brief can land as a follow-up commit.
