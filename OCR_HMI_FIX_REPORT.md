# OCR-HMI Fix Report: zero text on a real HMI photo

Branch `ocr-hmi-fix` (from main `5f6cb42`). Photo: `/tmp/tcm-plc.jpg` (POSCO TCM rolling-mill HMI, 4032x3024 JPEG).

## Reproduction

`IndustrialVision` on the photo returned `text_blocks: 0, fields: 0, tables: 0`, `extraction_status = completed_with_warnings`, in 232 s. Same zero-text result through the HTTP API (`POST /v1/jobs` → worker → `GET /v1/jobs/{id}/result`).

## Where the text was lost

The OCR saw the text the whole time; the pipeline threw it away:

1. **Region detection found no typed regions.** `detect_regions` on the working frame returned 2 regions, both `TABLE`-ish heuristics, zero `LABEL_VALUE`. So `_extract_fields` had nothing to read. Evidence: stage trace — `shallow_text` 1677 chars, GeneralOCR 633 tokens, `detect_regions` → 2 regions, `LABEL_VALUE` count 0.
2. **No profile matched** (`NO_PROFILE_MATCHED` warning), so `_extract_coil_tables` returned `[]` for the detected table regions — table text dropped too.
3. **Result assembly never populated `text_blocks` at all.** The `ExtractionResult(...)` construction passed only `tables`, `fields` and `warnings`; there was no path from OCR tokens to `text_blocks`. This is the stage where the 633 tokens (including "322", "TCM", "SECTION-3") were discarded.

## What was changed

### `engine/industrial/pipeline.py`

- One whole-frame OCR pass (`recognize_image(working)`) is now run once and shared: its tokens feed profile matching (previously `_ocr_text_shallow` did its own full pass) and, on the fallback, text extraction.
- When no profile matches, the OCR document's reading-order blocks are converted to schema `TextBlock`s (bbox, reading_order, confidence) and put on the result. Blocks with no alphanumeric character (glare/punctuation noise) are skipped. Profile-matched industrial documents keep their previous behaviour (fields/tables only).

### `engine/ocr/multiscale.py`

- `reocr_low_confidence` gained `max_retries: int = 48`: at most the 48 lowest-confidence tokens get a 2x-crop retry per call. A real photo with glare/moiré marked hundreds of tokens low-confidence and each retry was a separate tesseract call — the single `recognize_image` pass took 180 s. Retries on unreadable glare crops almost never improved the text. Seed/rendered inputs use far fewer than 48 retries, so their behaviour is unchanged.

## Regression test

`tests/test_ocr.py::test_industrial_vision_generic_hmi_returns_text_blocks` — renders a 640x400 four-line HMI-like image (not a placeholder), runs the real `IndustrialVision` + `PreprocessingPipeline.from_dict("industrial", {})` + `TesseractEngine` pipeline, and asserts non-empty `text_blocks` containing "MOTOR" and "1200".

- Pre-fix (stash of `engine/industrial/pipeline.py`): FAIL — `AssertionError: expected non-empty text_blocks ... assert []`.
- Post-fix: PASS.

## Checks run

- `.venv/bin/python -m pytest tests/`: **156 passed, 2 warnings** (baseline before the change: 155 passed).
- `.venv/bin/python -m ruff check engine/industrial/pipeline.py engine/ocr/multiscale.py tests/test_ocr.py`: all checks passed.
- `.venv/bin/python -m mypy engine`: Success, no issues in 64 source files.
- Real photo through the fixed pipeline: `status: completed_with_warnings, fields: 0, text_blocks: 13, tables: 0` in **45.1 s** (was 0 blocks in 232 s). Blocks contain the real screen text, e.g. `[ 322 [TCM SECTION-3 A PL | TCM | MENU | EXE`.
- End-to-end over the HTTP API (TestClient, temp DB): job `completed`, result file carries **13 text_blocks** with the same content.

Fields remain 0 on this photo: `read_compact` cannot recover legible strings from individual glare-corroded label crops. That is a separate limitation, not the zero-text bug.

## Remaining / follow-ups

- Field-level extraction on glare-heavy photos would need a glare-robust region reader (out of scope here).
- 45 s for a 12 MP photo is dominated by the primary tesseract pass at `psm 11` plus 48 retries; a faster backend (PaddleOCR/RapidOCR) would cut it further.
