# Coil table fix report (WIP — 30-min run limit)

Branch: `coil-table-fix` (from main `379347f`). Status: engine fix landed and verified locally; regression test, live API upload proof and lint/type checks are remaining (see end).

## Root cause (stage + evidence)

Reproduced locally on `/tmp/coil-table.png` ("Day Thong tin.png"): 24 columns, garbled header `V [ >' COL SSIN COLDROLL ...`.

1. **Garbage columns / wrong header — region + grid detection.** `detect_regions` returned the table region with bbox starting at y=25, i.e. it includes the filter-toolbar rows *above* the real table. `_read_grid` then treats grid row 0 (toolbar strip) as the header, and the left gutter (row-selector checkbox / scrollbar sliver, x < ~50) as 3–4 extra columns. Evidence: traced `_line_positions` on the real crop — vlines at x = 0, 23, 31, 43, 50 (gutter) and hlines at y = 1, 42 (toolbar) before the real header row (grid row 3: `SEQ Sts c.COIL ... Tapp.Targ.No`).
2. **Header content leaking into data rows** — direct consequence of 1: rows 1–2 (toolbar noise) were emitted as data rows.
3. **Warnings repeated ~10x** — `_extract_coil_tables` appended `unmapped header: ...` once per mapped data row (`for note in [n for mr in mapped_rows for n in mr.notes]`), so ~24 texts × ~19 rows.

## Fix (all in `engine/industrial/pipeline.py`)

- `_read_grid(..., header_index=N)`: the header row is no longer hard-wired to grid row 0; data rows are read below it (per-column field whitelists applied to rows after `header_index`).
- New `_pick_header_index`: scores the first 6 grid rows by how many cells resolve to profile column names (alphanumeric-normalized, containment-tolerant for OCR like `HotCoil` vs `hot_coil_no`); picks the real header row, falls back to row 0 for unknown layouts.
- New `_drop_noise_columns`: drops columns whose data cells are (nearly) all non-alphanumeric (gutter/checkbox/moiré); real narrow columns (`001`, `5`) survive. Column alternatives are re-indexed.
- `_extract_coil_tables`: picks the header row, re-reads the grid below it, drops noise columns; row-level notes and `validate_cells` warnings are deduplicated per table, and the result-level `warnings` list is deduplicated (`dict.fromkeys`) in `process`.

## Verified locally (real code path, before → after)

- Before: 24 columns, 20 rows, garbage header, duplicate warnings. After: **21 columns, 17 rows (header + 16 data rows)**, header = `SEQ STS C.COIL ... TAPP.TARG.NO`, all 15 coil rows 001–015 present with thickness/width/weight (e.g. `001 4.000 1243.5 21080`, `011 2.000 954.0 19260`), every warning text appears once (36 warnings, all unique).
- Column count is 21, not 20: the right-most truncated column (`Y...`) and the multi-level header (`Material/Unit Weight/Size/Grade` spanning two grid rows) are read as separate flat columns; structure is correct, naming follows the OCR'd text.
- OCR misreads under 79% glare (`S7CBOT?4`, `009`→`003`, `O11`) unchanged — out of scope per brief.
- `pytest tests/ -q`: exit 0 (baseline suite green after the change).
- Last data "row" `BS re` (scrollbar strip below the table) is still emitted; fix designed (`_drop_noise_rows`: drop rows with no digit and <8 alphanumeric chars) but not applied before the time limit.

## Remaining items

1. Regression test in an existing test file (synthetic coil image + noise gutter column; assert noise column dropped, single header row, no duplicate warnings; must fail pre-fix).
2. Optionally drop the trailing scrollbar-strip data row (`_drop_noise_rows`).
3. `.venv/bin/python -m ruff check .`, `.venv/bin/python -m mypy engine`, `python -m benchmark.validate`.
4. Live API upload proof (uvicorn + fresh SQLite + `/tmp/coil-table.png`).

## Commit

See `git log coil-table-fix` — commit hash added below after commit.
