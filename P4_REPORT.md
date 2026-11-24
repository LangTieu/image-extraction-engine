# P4_REPORT — Industrial Vision (mlai, LV3)

Date: 2026-11-24 · Continue run (first P4 run exhausted its step budget)

## Status: P4 complete — all checks green

| Check | Result (run this turn) |
|---|---|
| `pytest tests/` | 80 passed |
| `mypy engine` | Success: no issues found in 47 source files (was 16 errors) |
| `ruff check engine benchmark` | All checks passed |
| `benchmark/validate.py` | 35 passed, 0 failed |
| `python -m benchmark.industrial_eval` | exits 0 → `benchmark/results_industrial.json` |

## Delivered

1. `benchmark/industrial_eval.py` renders evaluation scenes from the seed
   ground-truth JSON at runtime (text blocks, `NAME: raw_text` field lines and
   GT tables as ruled grids on a dark HMI background) instead of feeding the
   blank 1x1 placeholder PNGs to the pipeline. `ExtractionStatus` is now
   exported from `engine.schema`.
2. All 16 mypy errors in `engine/industrial/` fixed (`pipeline.py`,
   `regions.py`, `profiles.py`, `compact_ocr.py`); `ExtractionStatus` is a
   public `StrEnum` (named type with `__name__`, values compare as strings).
3. `ndim == 3` channel assumptions generalized in `alarms.py` and
   `compact_ocr.py` (2-D, HxWx1 and any multi-channel input supported).

## Measured eval numbers

- routing accuracy 0.500 — `industrial_hmi` 5/5 correct; `coil_table` 0/5
  (OCR cannot read the small dark-background table text, so the coil
  vocabulary rule never fires and the pipeline takes the documented
  `NO_PROFILE_MATCHED` fallback).
- field F1 0.000, unit accuracy 0.000 (direct consequence of the above);
  unknown_flagged 1.000 — every unmatched field name is flagged, none dropped.

Full detail and limitations: `docs/reports/p4_industrial.md`.

## Fix round — dark-background OCR (2026-11-24)

What changed (all inside `engine/industrial/`):

1. `compact_ocr.py`: crop binarization is now polarity-normalized — when
   OTSU yields a mostly-dark image (bright-on-dark HMI text), it is inverted
   to dark-on-light before tesseract. New `shallow_text()` whole-frame OCR
   for profile matching: min-max normalized, inverted when mean luminance
   < 127.5, no binarization (full-frame grid lines dominate it). Confusable
   alternatives now also generate whole-class swaps (every O -> 0).
2. `screen.py`: screen-quad detection rejects quads whose interior is mostly
   dark (< 127 mean luminance) — on dark HMI screens the OTSU bright mask
   was the text rows, not the screen — and falls back to the full frame.

New eval numbers (`benchmark/industrial_eval.py`, honest):

- routing accuracy 1.000 (was 0.500): `industrial_hmi` 5/5, `coil_table`
  5/5 (was 0/5; brief target ≥ 3/5).
- field F1 0.933 (was 0.000), unit accuracy 0.875 (was 0.000),
  unknown_flagged 1.000 (unchanged).
- Counts: tp 35, fp 0, fn 5, unit_ok 35/40 — the fn are the `weight_t`
  rows whose rendered values exceed the profile max-40 bound (flagged as
  range warnings).

### Checks (all run this turn after the fix)

| Check | Result |
|---|---|
| `pytest tests/` | 80 passed in 1.22s |
| `benchmark/validate.py` | 35 passed, 0 failed |
| `ruff check engine benchmark tests` | All checks passed |
| `mypy engine` | Success: no issues found in 47 source files |

Full detail: `docs/reports/p4_industrial.md`.
