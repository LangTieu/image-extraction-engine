# D2 fix review report — review round 1 fixes (LightVela review)

Branch `d2-backend-registry`, on top of `b21b5cd`. NOT merged, per brief.

## Fixes applied

### H1 — worker uses the registry path again
`service/worker/runner.py:_load_image` now calls
`engine/preprocessing/io.py:load_input(path)`, restoring the
`SourceNotFoundError` (missing file) and `InputLimitError` (oversized file)
guards that the previous direct-backend call skipped. Worker-path tests
added.

### H3 — real equivalence test with an independent oracle
`tests/test_backends.py` no longer cross-checks Pillow against itself:

- Fixture: a two-page PDF built with **reportlab** (vector drawing,
  independent of the engine's rasterization path).
- Oracle: the test renders the same PDF directly with **pypdfium2**
  (`PdfDocument(...).render(scale=dpi/72)`) and compares bitmaps with the
  backend output (max channel diff ≤ 1), plus sha256/page-index fields.
- `load_input(pdf)` vs `backend.load(pdf)` equality is checked byte for byte
  (pixels, sha256, page indices).

### H4 — text layer name
`engine/ocr/pdf.py:PdfiumTextLayer` now declares `name = "pypdfium2"`
(tested). **Registry decision kept**: `get_backend` stays file-format based;
the OCR text layer is not registered as an input backend (an input backend
produces `LoadedImage`s from files, a text layer produces `PageText`s —
different contracts).

### M1 — MIME precedence
`get_backend(path, mime)`: a known extension always wins; MIME is only
consulted for extension-less paths (documented in the docstring). Test
`test_extension_wins_over_mime` pins `.png` + `application/pdf` → Pillow.

### M2 — registry hardening (`engine/backends/base.py`)
- Defaults are ensured lazily inside `base.py` (`_ensure_defaults`, guarded
  by a module flag), so importing `base` directly also yields a usable
  registry, and defaults are re-added only once (never duplicated after
  `unregister_backend`).
- `register_backend` validates the protocol (`TypeError` otherwise), replaces
  same-`name` entries, and **prepends** new names (first-match priority).
- New `unregister_backend(name) -> bool` and `clear_registry()` helpers,
  exported from `engine.backends`.

### M3 — honest `page_count`
- `PypdfiumPdfBackend.page_count`: real `len(PdfDocument)` (raw count, may
  exceed the `MAX_PDF_PAGES` load limit — that cap still fires in `load`);
  `FileNotFoundError` for missing files, `CorruptImageError` for garbage.
- `PillowImageBackend.page_count`: real `n_frames` (multi-frame GIF/APNG),
  1 for single-frame images, same typed errors.

### M4 — `_from_pdf` signature
`engine/preprocessing/io.py:_from_pdf(path, sha256="", dpi=DEFAULT_DPI)`
delegates to the pypdfium2 backend; `sha256` is accepted for backwards
compatibility and ignored (the backend computes it). Byte-for-byte equality
with the registry path is tested.

### M5 — test gaps filled (tests/test_backends.py, 24 tests)
`.jpeg` loading (format `jpg`), uppercase/mixed-case extensions, MIME with
parameters (`application/pdf; charset=binary`), unknown MIME without
extension, `load_input` image path (page `None`), missing-file
`SourceNotFoundError` through `load_input`, corrupt image/PDF
`CorruptImageError`, GIF frame count, unsupported-extension rejection from
`PillowImageBackend.load`, `register_backend` type check.

### L1 — dead constants removed
`IMAGE_EXTENSIONS`/`PDF_EXTENSIONS` dropped from `engine/preprocessing/io.py`
(verified no importers; the image backend keeps its own `IMAGE_EXTENSIONS`).

### L2/L3 — docstrings
`get_backend` docstring documents the extension-over-MIME precedence and the
`format` field semantics; `_from_pdf` docstring states the deprecation.

## Gates (this round, exit codes)

- `pytest tests/ -q -p no:warnings` → exit 0, **198 passed** (24 in
  tests/test_backends.py)
- `python -m benchmark.validate` → exit 0, **35 passed, 0 failed**
- `ruff check .` → exit 0
- `mypy engine benchmark tests` → exit 0 (90 source files)

## Live smoke (LV3)

Started `uvicorn service.api.app:app` on 127.0.0.1:3011 and uploaded real
files to `POST /v1/jobs` (field `files`):

- `smoke.pdf` (application/pdf, reportlab-generated) → `job_0c44eb6fa596`
- `smoke.png` (image/png) → `job_fb0e8d8c9374`

Both polled to `status: completed`, `progress: 100`, `error: null`.

## Known-not-done

- L3 (`format` wording on unsupported errors) was folded into the M1/M2
  rewrite: `format` is the extension when the path has one, otherwise the
  cleaned MIME — covered by the structured-error tests.
