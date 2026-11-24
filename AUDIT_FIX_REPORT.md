# Audit-fix report A — measurement & geometry (mlai, LV3)

All five audit items fixed. Required checks (all pass, final run):
`pytest tests/ -q` → **80 passed** (exit 0) · `benchmark/validate.py` → **35 passed, 0 failed** (exit 0) · `ruff check engine benchmark tests` → **All checks passed!** · `mypy engine` → **Success: no issues found in 47 source files**.

## 1. `benchmark/industrial_eval.py` — GT/pred both dropped first data row
- **What changed:** `_gt_fields` iterated `table.rows[1:]` assuming row 0 is a
  header row; the unified schema keeps headers in `Table.columns`, so row 0 is
  data. Same slicing existed in the prediction extraction. Both now iterate
  all rows.
- **Before:** routing=1.000 f1=0.933 unit_acc=0.875 unknown_flagged=1.000
- **After:** routing=1.000 f1=0.933 unit_acc=0.875 unknown_flagged=1.000
  (seed GT rows were complete, so field-level F1 unchanged; the off-by-one is
  gone — metrics no longer depend on dropping a real data row).

## 2. `engine/preprocessing/mapping.py` + `engine/preprocessing/transforms.py`
- **Bug 1 (composition order):** `TransformLog.add` composed
  `self._cumulative = matrix @ self._cumulative`, which applies an older step
  *after* a newer one when mapping back. Fixed to
  `self._cumulative = self._cumulative @ matrix` (oldest-first, column-vector
  convention), so the cumulative always maps latest-processed → original.
- **Bug 2 (crop homography direction):** `trim_borders`/`crop_region` built a
  post→pre translation matrix and then passed it through `_inverse_affine`,
  inverting it again so the logged step pointed the wrong way. They now return
  `_homography_from_affine(matrix)` directly (post→pre, as the docstring
  documents). `rotate`/`upscale`/`correct_perspective` keep `_inverse_affine`
  (their matrices are pre→post).
- **Bug 3 (content-mode bottom/right off-by-one):** bottom/right used
  `argmax(rows[::-1]) + 1`, which counts from the last pixel, shrinking the
  crop. Fixed to `size - argmax(reversed) + margin` per the brief.
- **Hand-computed verification:** crop offset (10,20) then 3× upscale → post
  (4,4) maps to (11.333, 21.333) exactly; inverse maps back to (4,4);
  `round_trip_error` = 0.0 (float-exact; worst over 8 seed images also 0.0).
  `trim_borders` content-mode: content block rows 10–19 / cols 20–29 in a
  50×60 image → crop shape (10,10) and post (0,0) → pre (20,10).

## 3. `engine/tables/tatr.py` — `_structure()`
- Cell bboxes are now offset by `region.bbox` into full-image coordinates so
  `assign_tokens` compares like with like.
- Cells are emitted for all detected row bands (`range(len(rows))`), fixing
  the dropped last row.
- `_mark_span` guards empty generators: if a spanning-cell box starts above
  all detected rows (or left of all columns), the span is skipped instead of
  raising `ValueError` from `max()`.
- **TATR eval (after):** recall=1.00 structure=1.00 content=1.00,
  latency=724 ms/table (n=5). No before/after delta recorded because the
  module could not run at all pre-fix (the `_mark_span` ValueError aborted
  structure recognition on spanning cells); it now completes cleanly.

## 4. `engine/schema/models.py` — BBox validator
- `_positive_extent` previously did `return v`. It now enforces
  `x1 > x0` and `y1 > y0`, raising `ValueError` otherwise (verifies via
  `info.data` against the already-validated `x0`/`y0`).

## 5. `benchmark/tables_eval.py` — best-IoU matching with exclusion
- The loop took the *first* extracted table with IoU > 0.5 and broke, so one
  extracted table could "match" several GT tables. Rewritten: for each GT
  table pick the best-IoU extracted table above the threshold, with a `used`
  set so each extracted table matches at most one GT table; unmatched GT
  tables score 0.
- **Tables eval (after):** ruled / borderless / tatr / hybrid all
  recall=1.00 structure=1.00 content=1.00 on the seed set.

## Checks (final run, this turn)
| Check | Result |
|---|---|
| `.venv/bin/python -m pytest tests/ -q` | 80 passed (exit 0) |
| `.venv/bin/python benchmark/validate.py` | 35 passed, 0 failed (exit 0) |
| `ruff check engine benchmark tests` | All checks passed! |
| `mypy engine` | Success: no issues found in 47 source files |

Supporting runs: `preprocess_cer` (mean CER raw 0.187 → preprocessed 0.1902),
`industrial_eval`, `tables_eval`, `ocr_cer` (CER 0.000 on all categories),
plus a real-pipeline round-trip over seed images (worst error 0.0).

No files were created under `tests/`. No packages installed, nothing deleted,
nothing committed or pushed.
