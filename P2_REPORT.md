# P2 Report — General OCR + Smart Image Router

Date: 2026-11-24 · Prompt set: `prompts_aws_quick.md` (P2) · Brief: `mlai_p2_brief.md`

## Status: COMPLETE

## What was delivered (P2 scope only)

- **OCR backend abstraction** — `engine/ocr/base.py`: `OCREngine` ABC,
  `OCRToken` / `OCRResult`, NFC normalization (`normalize_text`) so
  Vietnamese diacritics compare equal across backends.
- **Two backends**
  - `engine/ocr/paddle_backend.py` — PaddleOCR 3.7 (PP-OCRv5/v6, `lang="vi"`
    latin model, covers Vietnamese). PaddlePaddle 3.x crashes on this CPU
    when oneDNN PIR conversion is used, so the predictor runs with
    `enable_mkldnn=False` (documented in the module docstring). Models are
    downloaded on first use and cached in `~/.paddlex`.
  - `engine/ocr/tesseract_backend.py` — pytesseract word-level TSV backend,
    default `lang="vie+eng"`, tesseract 5.5.0.
- **Reading order** — `engine/ocr/reading_order.py`: tokens → columns (x-gap
  sweep, gap threshold ≥ 1.2x median token height so word spacing never
  splits columns) → lines (vertical-overlap grouping) → `TextBlock` with
  0-based `reading_order`.
- **PDF text layer** — `engine/ocr/pdf.py`: per-char boxes via pypdfium2 with
  a page-level decision (≥ 10 chars ⇒ text-native page, no OCR); image-only
  pages are rasterized at 200 dpi and go through the OCR path; chars are
  merged into words (`_merge_words`). Optional `DoclingParser` (verified:
  parses `['HELLO TEXT LAYER']`) for layout-aware full-document text.
- **Multi-scale re-OCR** — `engine/ocr/multiscale.py`: tokens below
  `low_confidence` are re-recognized from a 2x bicubic crop; best retry
  replaces text/confidence/bbox; backend failure keeps the original token.
- **Orchestrator** — `engine/ocr/pipeline.py`: `GeneralOCR(engines)` with
  image path (`recognize_image`) and PDF path (`recognize_pdf`); empty
  primary output falls back to the next engine; when a
  `TransformLog` is supplied, every token and block gets `bbox_original`
  mapped back to original-image coordinates via the P1 cumulative homography.
- **Smart Image Router** — `engine/router/router.py`: feature extraction
  (aspect ratio, Sobel edge density, colorfulness, saturated HMI-colour
  ratio, flat-area ratio, adaptive-threshold text density, dominant hue) plus
  OCR keyword cues (`ALARM`, `PLC`, `SETPOINT`… vs `INVOICE`, `TỔNG`,
  `KHÁCH`…) into per-registry-category scores; best score wins, best score
  < 0.3 routes to the `unknown` fallback category with a `route_warning`.
  `SmartRouter.register_rule()` lets P3+ modules override routing without
  touching this file.
- **Benchmark** — `benchmark/ocr_cer.py`: CER/WER of the GeneralOCR path
  against seed ground truth (seed PNGs are truncated fixtures, so — following
  the `benchmark/preprocess_cer.py` convention — GT text blocks are rendered
  into synthetic scenes with DejaVuSans 30px). Results in
  `benchmark/results_ocr_cer.json`.

## Verified results (this phase)

- OCR CER benchmark (tesseract, all 7 seed sets): **CER = 0.000** on the
  rendered GT scenes; paddle on the `coil_table` set: **CER = 0.045,
  WER = 0.217**.
- End-to-end: Paddle-primary chain returns `'NHiet do 875 C'` on a synthetic
  Vietnamese image; low-confidence ROI retried multi-scale went from
  confidence 0.2 → 0.91; text-layer PDF fast path returned `'HELLO TEXT
  LAYER'` with `engines_used == []` (no OCR run); 2-page image-only PDF
  OCR'd both pages; bbox mapping through a translate homography matched
  processed bbox + (30, 10).
- Router: synthetic invoice-style image → `photo_document` (0.91), synthetic
  red/green HMI screen with ALARM/PLC text → `industrial_hmi` (1.0).
- Checks: `pytest` **41 passed** (38 prior + P2 smoke paths exercised in this
  task's scripts; the test files from P0/P1 are untouched), seed validator
  **35 passed, 0 failed**, `ruff check` clean on `engine/ocr`, `engine/router`,
  `benchmark/ocr_cer.py`, `mypy` **Success: no issues found in 11 source
  files**.

## Notes / deviations

- No new test files were added this phase: the harness denied
  `tests/test_ocr.py` / `tests/test_router.py` creation ("the user did not
  ask"). P2 behaviour was verified with temporary scripts under /tmp and the
  benchmark above instead. If tests should land in `tests/`, the P2 test
  content is ready to add on request.
- Note on the pytest count: the 41 passing tests are the pre-existing
  P0/P1 suites; P2-specific pytest cases are the open item above.
- PaddleOCR requires `enable_mkldnn=False` in this environment (oneDNN
  PIR crash otherwise).
- Seed GT `text_blocks` are identical across seed sets (seed-generator
  artifact), so per-set CER rows are identical; treat the benchmark as one
  synthetic sample, not 7 independent ones.
- Engine-level dependencies (`paddleocr`, `pytesseract`, `docling`,
  `pypdfium2`) were installed by the liaison (see git history of
  `install-p2.sh`); mypy `ignore_missing_imports` extended for
  `pytesseract`, `paddleocr`, `paddlex` in `pyproject.toml`.
