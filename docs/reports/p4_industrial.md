# P4 — Industrial Vision report (continue run)

Date: 2026-11-24 · branch main · module `engine.industrial`

## Checks (all run this turn, exit status verified)

| Check | Result |
|---|---|
| `pytest tests/` | 80 passed |
| `mypy engine` | Success: no issues found in 47 source files (was 16 errors) |
| `ruff check engine benchmark` | All checks passed |
| `benchmark/validate.py` | 35 passed, 0 failed |
| `python -m benchmark.industrial_eval` | exits 0; routing=0.500 f1=0.000 unit_acc=0.000 unknown_flagged=1.000 → `benchmark/results_industrial.json` |

## What changed in this continue run

1. **`benchmark/industrial_eval.py` now renders scenes from the ground-truth JSON at
   runtime** (same convention as `tables_eval`/`ocr_cer`): text blocks, then
   `NAME: raw_text` field lines, then GT tables as ruled grids, drawn on a dark
   HMI-like background. The blank 1x1 seed PNGs are no longer fed to the pipeline.
   This required exporting `ExtractionStatus` from `engine.schema` (it existed in
   `engine/schema/models.py` but was missing from `__init__.py`).
2. **16 mypy errors in `engine/industrial/` fixed** (`pipeline.py`: status
   typing via the new `ExtractionStatus` StrEnum, `ProcessingMeta` model instead of a raw dict, GeneralOCR API
   call, table-schema selection, bounding-box typing; `regions.py`: morphologyEx
   return type, alarm-box tuple type; `profiles.py` and `compact_ocr.py`: stale
   `type: ignore`s and a normalize in-place bug).
3. **`ndim == 3` channel assumptions generalized**: `alarms.py:indicator_state`
   and `compact_ocr.py` now handle 2-D, HxWx1 and any multi-channel input
   (channels folded via mean / grayscale) instead of assuming exactly 3.

## Measured results (honest)

- `industrial_hmi`: 5/5 route_ok (router falls back to the generic HMI profile;
  fields_gt = 0 in these GTs so field F1 is defined only by coil samples).
- `coil_table`: 0/5 route_ok. The rendered scenes are real (invoice text, coil
  field lines, an 8-column ruled coil table) but the P2 OCR backends cannot read
  the small dark-background text reliably, so the coil-vocabulary router rule
  (`engine/industrial/router_rules.py`) sees too few cues and the pipeline takes
  the `NO_PROFILE_MATCHED` fallback; field F1 is therefore 0.000.
- Detector warnings fire as designed (glare %, moiré score, screen-boundary
  fallback), and `unknown_flagged=1.000` — the validation layer flags every
  unmatched field name instead of silently dropping it.

## Fix round (dark-background OCR, 2026-11-24)

What changed (all inside `engine/industrial/`):

1. `compact_ocr.py`: crops now binarize polarity-normalized — when OTSU
   produces a mostly-dark image (bright-on-dark HMI text), the binary is
   inverted so tesseract and the segment classifier see dark ink on a light
   background. New `shallow_text()` does whole-frame OCR for profile
   matching (no binarization — full-frame table grid lines dominate it — and
   min-max normalized, inverted when the mean luminance is below 127.5).
   Confusable alternatives now also include whole-class swaps (every O -> 0).
2. `screen.py`: on dark HMI screens the OTSU bright mask finds the text, not
   the screen, so the dominant quad was a thin strip of text rows. Quads
   whose interior is mostly dark (mean luminance < 127) are now rejected and
   the pipeline falls back to the full frame.

New eval numbers (`benchmark/industrial_eval.py` → `results_industrial.json`):

- routing accuracy 1.000 (was 0.500) — `industrial_hmi` 5/5, `coil_table`
  5/5 (was 0/5; brief target was at least 3/5).
- field F1 0.933 (was 0.000), unit accuracy 0.875 (was 0.000),
  unknown_flagged 1.000 (unchanged — every unmatched field is flagged).
- Counts: tp 35, fp 0, fn 5, unit_ok 35/40. The 5 fn are the two
  `weight_t` rows per table whose rendered values exceed the profile's
  max-40 validation bound (flagged as range warnings, counted as misses).

Checks after the fix: pytest 80 passed, `benchmark/validate.py` 35 passed,
ruff green, mypy clean (see `P4_REPORT.md`).

## Known limitations (carried to P5 candidates)

- Field-level accuracy needs either higher-resolution rendered scenes with the
  P1 contrast pipeline tuned for dark HMI themes, or real seed images.
- Seed PNGs remain 1x1 placeholders (P0 scaffolding); all scene pixels are now
  synthesized at eval time from the GT JSON.
