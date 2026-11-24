# P3 Report — Table Extraction

Date: 2026-11-24. Brief: `mlai_p3_brief.md` (P3 prompt in
`prompts_aws_quick.md`, lines 178–~230). P4 not started.

## What shipped

- `engine/tables/` package:
  - `base.py` — `TableBackend` ABC, `CellGrid`/`CellBox`/`TableRegion`,
    `TableConfig` (`backend`: ruled | borderless | hybrid | tatr) and
    `TableBackendUnavailable`.
  - `ruled.py` — OpenCV ruled-table backend: adaptive threshold,
    morphological H/V line masks, HoughLinesP lattice, clustered row/column
    boundaries, cell grid. No models.
  - `borderless.py` — borderless backend: OCR-token clustering into
    rows/columns, gap-based splitting, wide-token col_span (merged cells).
    No models.
  - `hybrid.py` (default) — runs all available backends, matches regions by
    IoU > 0.5, keeps the higher-scored grid and folds in extra cells;
    gracefully skips backends that raise `TableBackendUnavailable`.
  - `tatr.py` — Table Transformer backend, weights probed with
    `local_files_only=True`; **never downloads**. Raises
    `TableBackendUnavailable` without cached weights (verified by the
    smoke check below).
  - `cells.py` — overlap-based token→cell assignment (straddling tokens go
    to the cell they mostly cover), first row as header with
    `column_N` fallbacks, per-cell mean confidence, `normalize_column_key`
    ("Hot Coil No." -> `HOT_COIL_NO`).
  - `pipeline.py` — `TablePipeline.extract` (fills unified-schema `Table`
    with cells/bbox/confidence), `reocr_cells` (P2 multi-scale re-OCR hook
    for low-confidence cells, before coordinate mapping),
    `merge_pages` (duplicate `table_name` -> `_pN`; same normalized-header
    tables merge as continuations, rows appended), TransformLog mapping
    back to original image coordinates.
  - `viz.py` — `render_debug` overlays (region/cell/header/token boxes).
- `benchmark/tables_eval.py` + `benchmark/results_tables.json` +
  `benchmark/viz_tables/` overlays; report in `docs/reports/p3_tables.md`.

## TATR evaluation (resolved 2026-11-24, brief `mlai_p3_tatr_brief.md`)

- `timm 1.0.31` installed in `.venv` (verified import).
- Weights for `microsoft/table-transformer-detection` and
  `microsoft/table-transformer-structure-recognition` fetched into the
  local HF hub cache (~441 MiB; the earlier /data disk guard no longer
  applies). `_weights_cached` now returns True, so `TATRBackend`
  activates and `HybridBackend._maybe_add_tatr()` appends it as a
  candidate (verified sub-backend list: RuledGridBackend,
  BorderlessClusterBackend, TATRBackend). BLOCKED.md deleted.
- `benchmark/tables_eval.py` re-run with all four backends: tatr scores
  1.00/1.00/1.00 (recall/structure/content) on both categories at
  ~2451 ms/table (table_image) and ~1437 ms/table (coil_table) on 2-core
  CPU; hybrid stays 1.00 at ~471/~440 ms/table with TATR included.
  Details in `docs/reports/p3_tables.md`.
- The UNEXPECTED `num_batches_tracked` keys in the transformers load
  report are benign (buffer-only keys absent from the checkpoint).

## Test file blocked by tooling

Resolved 2026-11-24 (brief `mlai_p3_test_brief.md`): `tests/test_tables.py`
is now in the repo — 18 tests covering ruled/borderless/hybrid backends,
token→cell assignment, header and `column_N` fallbacks, empty cells as
explicit nulls, `normalize_column_key`, pipeline `extract` with TransformLog
bbox mapping, no-header warnings, `merge_pages` continuation/`_pN` rename,
the TATR no-download guard (local_files_only spy), and the rendered coil
table no-column-shift regression. Full suite: 80 passed, 0 failed; mypy
engine and ruff clean. Note: the earlier "fully written and ready to paste"
suite was never persisted anywhere (no file, no log); it was authored fresh
in this run. P4 still not started.

## Checks run (2026-11-24, TATR turn)

- `.venv/bin/python -m pytest -q` — exit 0, **80 passed**.
- `.venv/bin/python benchmark/validate.py` — 35 passed, 0 failed.
- `.venv/bin/ruff check engine benchmark tests` — All checks passed;
  `ruff format --check engine benchmark tests` — 57 files already formatted.
- `.venv/bin/python -m mypy engine/tables benchmark/tables_eval.py` —
  Success: no issues found in 10 source files.
- `benchmark/tables_eval.py` — recall/structure/content 1.00 for
  ruled/borderless/tatr/hybrid on both table categories (rendered scenes).

## TATR guard note

`TATRBackend` still loads with `local_files_only=True` and never
downloads (covered by the spy test in `tests/test_tables.py`); with the
weights now cached it simply succeeds.

## Deviations from the brief

1. Benchmark on rendered GT scenes, not raw seed PNGs (truncated fixtures).
