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

---

# Audit-fix report B — industrial pipeline (mlai, LV3)

Second batch (brief B). All items fixed. Required checks (final run, this
turn): `pytest tests/ -q` → **80 passed** (exit 0, unchanged from baseline) ·
`ruff check engine tests` → **All checks passed!** · `mypy engine` →
**Success: no issues found in 47 source files** ·
`benchmark/industrial_eval.py` → **routing=1.000 f1=0.933 unit_acc=0.875
unknown_flagged=1.000** · `benchmark/tables_eval.py` → ruled/borderless/tatr/
hybrid all **recall=1.00 structure=1.00 content=1.00**.

## 1. `engine/industrial/pipeline.py` — `_read_grid` header alignment
`headers = [h for h in rows[0] if h]` dropped empty header cells, shifting
every data column after the first empty header (and an `IndexError` when
headers ran out before columns). Headers now stay positionally aligned with
the data columns (empty header cells kept as placeholders), and `ftype`
lookups are bounds-checked (`col_index < len(field_types)`) instead of
assuming the list is long enough.

## 2. `engine/industrial/values.py` — separators and compound units
- `_strip_thousands` returned `1,234` → `"1.234"` (the brief's 1000× misread).
  Bare `1,234` with exactly 3 trailing digits is now treated as thousands
  grouping and the comma is *removed* (`1234`); `12,5` stays decimal;
  ambiguous forms like `12,3456` are flagged in `notes` instead of guessed.
- `_UNIT_PATTERN` only accepted one letter-run as a unit, so `10 kg/m2` and
  `5 m/min` failed entirely (`value=None`). Compound units (`x/y`, optional
  exponent `^2`) are now accepted, split on `/`, and accepted when every part
  is a known unit; unknown units keep the parsed value but set an
  `unknown unit` note (the value is no longer discarded).
- Default units (`mm`, `°c`, …) are normalized (`degc` → `°c`) and now emit a
  `unit defaulted to …` note so downstream review can distinguish a real
  unit token from an assumption.

## 3. `format_regex` now wired into extraction
`DEFAULT_FIELDS[...]['format_regex']` existed but nothing called it during
extraction. `engine/schema/industrial_fields.validate_value` is now invoked
from both `coil_table.extract` and `_extract_fields`, so a value failing its
`format_regex` (or plausible range) lands in the result `notes` /
`needs_review` instead of being silently accepted.

## 4. `needs_review` escalation
`_extract_fields` built `FieldValue.needs_review` from parse notes and OCR
flags only; a failing `format_regex` did not set it, and the run status
stayed `COMPLETED_WITH_WARNINGS`. Now any flagged field escalates the result
status to `NEEDS_REVIEW`; pure default-unit notes alone do not.

## 5. `regions.py` / `alarms.py` — `red2` and unreadable rows
- `_ALARM_COLORS` missed the `red2` HSV bucket, so dark-red banners fell out
  of the alarm-band lookup. Added to the colour set.
- Severity map extended (`red2` → `critical`) and rows missing the *code*
  cell now get a `code_unreadable` flag (timestamp already had one).

## 6. `engine/industrial/screen.py` — dark-screen quads
`_detect_quad` OTSU-thresholded for *bright* regions, so a dark-background
HMI screen locked onto text rows and the interior-brightness guard
(`inside < 127 → None`) rejected the quad, forcing full-frame fallback.
Detection is now inversion-aware: for dark frames the grayscale is inverted
before thresholding so the screen interior is the dominant blob, and the
guard was replaced with an inside-vs-outside contrast check (a flat frame
with no brightness difference is rejected regardless of polarity).

## 7. `engine/tables/borderless.py` — score no longer token-count
`score=min(1.0, len(tokens)/12.0)` rated a 12-token pile of noise a perfect
table. Replaced with a structural score: the share of columns holding >1
token (real columns are reused across rows) times the token-area coverage of
the region, `0.7*column_support + 0.3*coverage`, rounded to 3 decimals. The
`min_region_score` gate still applies.

## 8. `engine/tables/hybrid.py` — same-backend dedupe
Two grids from the *same* backend with IoU > 0.9 were both fed into the
cross-backend reconciliation (the 0.8 threshold there never fired because
same-backend grids overlap themselves), inflating the winner's confidence.
New `_dedupe` drops near-identical same-backend regions (IoU > 0.9, best
score kept) before the cross-backend merge.

## 9. `engine/ocr/multiscale.py` — retry must substitute
The retry token was appended unconditionally even at *lower* confidence,
adding a duplicate/incorrect token. The retry now substitutes only when its
confidence is strictly higher than the original's, its mapped bbox stays
within ~2.25× the original token area (bigger means the crop swallowed
neighbouring text), and the original token is kept otherwise.

## 10. `engine/router/router.py` — keywords, zero-score, reason spam
- `extract_keywords` used substring matching, so `run` matched `running`,
  `đơn` matched anything containing those letters, etc. Matching is now
  word-bounded (`(?<!\w)kw(?!\w)`).
- The zero-score guard (`if not known`) only fired when *no category was
  registered*; with registered categories that all scored 0.0, `max()` picked
  an arbitrary 0-confidence winner. The guard now also fires when every
  category scores 0.0, routing to `unknown` with
  `"best score 0.0000 below 0.3"` as the route warning.
- The HMI reason line dumped the full hit list (spam on keyword-rich
  screens); it now lists unique hits capped at 4, and the 0.4 boost is
  applied once per category regardless of hit count.

## 11. `engine/industrial/profiles.py` — YAML coercion, deterministic match
- `tuple(spec.get("aliases", ()))` crashed on YAML scalars (a single alias or
  a numeric id), and numeric aliases (`aliases: [12345]`) came out of YAML as
  ints and broke string matching. New `_as_str_tuple` coerces scalars/lists
  to stripped string tuples everywhere (field aliases, `min_value`/`max_value`
  via a guarded float cast, header aliases, `id_columns`, `categories`,
  `title_cues`, `layout_anchors`, `colors`).
- `match_profile` iterated the pool in list order and used strict `>`, so
  equal scores resolved by list order. The pool is now name-sorted first, so
  ties resolve deterministically by profile name.

## 12. `engine/industrial/compact_ocr.py` — misleading ternary
`config = _PSM_SINGLE_LINE if whitelist else _PSM_SINGLE_LINE` — both arms
were identical (PSM 8 was tried for numeric whitelists and *reduced*
accuracy on machine-printed digit strings). The dead ternary is replaced
with a flat assignment plus a comment explaining why the same PSM is used in
both branches.

## Checks (final run, this turn)
| Check | Result |
|---|---|
| `.venv/bin/python -m pytest tests/ -q` | 80 passed (exit 0) |
| `ruff check engine tests` | All checks passed! |
| `mypy engine` | Success: no issues found in 47 source files |
| `benchmark/industrial_eval.py` | routing=1.000 f1=0.933 unit_acc=0.875 unknown_flagged=1.000 |
| `benchmark/tables_eval.py` | all four backends recall/structure/content = 1.00 |

No files were created under `tests/`. No packages installed, nothing deleted,
nothing committed or pushed.
