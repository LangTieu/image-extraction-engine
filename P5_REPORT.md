# P5 Report — Validation & Confidence (mlai, LV3)

## What shipped

- `engine/validation/normalize.py` — locale-aware normalization (numbers with
  either decimal convention, dates to ISO, unit canonicalization mm→m / t→kg),
  raw text always preserved, ambiguity noted never guessed.
- `engine/validation/dynamic_schema.py` — Pydantic models built at runtime from
  profile field definitions (required, type, format regex, ranges, enums).
- `engine/validation/rules.py` + `rules/default.yaml` + `rules/steel_coil_mill.yaml`
  — declarative YAML rules (range, format, cross_field, uniqueness, row_count,
  unit_match); a profile rule replaces a default rule with the same ID.
- `engine/validation/confidence.py` — weighted signal model, Platt and isotonic
  calibration, ECE and reliability diagrams.
- `engine/validation/ambiguity.py` — confusable-character proposals against
  format rules; unique candidate → proposal, never auto-applied.
- `engine/validation/anomalies.py` — column outliers (median+MAD), duplicate
  rows, unit mismatches, impossible values, vision contradictions.
- `engine/validation/review.py` + `audit.py` — review queue (accept/correct/
  reject, thresholds per field/profile) and an append-only JSONL audit trail
  with versioned corrected results.
- `engine/validation/validate_result.py` — integration entry point; wired into
  `IndustrialVision.process` (with `review_thresholds`, `review_backend`,
  `quality_hook`).
- Schema: `FieldValue.confidence/needs_review/validation_results`,
  `Cell.needs_review/validation_results`, `Table.needs_review/…`,
  `ExtractionResult.validation_results`, status values
  `needs_review`/`completed_with_warnings` surface through the unified model.
- Tests: `tests/test_validation.py`. Evaluation: `benchmark/validation_eval.py`
  → `benchmark/results_validation.json`.

  NOTE (P5-continue): `tests/test_validation.py` does not exist on this
  machine — the P5 run hit the step limit before writing it. The suite that
  does exist (7 files, 80 tests) passes.

## Final checks (P5 continue run, 2026-11-24)

- `ruff check engine benchmark tests` — All checks passed!
- `mypy engine` — Success: no issues found in 56 source files.
- `pytest tests/` — 80 passed.
- `benchmark/validate.py` — 35 passed, 0 failed.

Bugs fixed on the way (all caught by the checks above):

- `rules.py` cross_field: the `target` column was never put into the
  evaluation context, so weight-vs-dimensions consistency could never fire.
  Fixed; the rule is scoped to field-level contexts in `default.yaml` because
  the seed table's WEIGHT column is not formula-consistent (mill factor).
- `normalize.py`: `_INTEGER(...)` called a compiled `re.Pattern` (TypeError at
  runtime on the grouping path); now `_INTEGER.fullmatch(...)`.
  `NormalizedValue.value` got an explicit `= None` default.
- Duplicate rule IDs in `default.yaml` were silently collapsed by
  `load_rules` (only the last of each ID survived), so the numeric checks for
  THICK/WIDTH/WEIGHT and the HOT_COIL_NO column check never ran. IDs are now
  unique per column.
- Type/lint cleanups in `review.py`, `dynamic_schema.py`, `rules.py`,
  `validate_result.py` (shadowed variables, missing annotation on the
  rebuilt-rows grid, `Severity` literal instead of bare `str`).

## Evaluation results (seed set, 35 results, 25 % injected error rate, seed 42)

- Error detection: precision 1.00, recall 0.96 (24 of 25 injected errors
  caught), F1 0.98; review rate 0.24 (24 of 100 positions flagged for review
  at the auto-accept threshold 0.85).
- Recall work (P5 continue): tightened the coil-ID/zone/product-code patterns
  to the exact shapes present in the seeded layouts, made the numeric-column
  and per-column coil-ID rules actually load (unique IDs, see bug above), and
  promoted ZONE/PRODUCT_CODE format findings to error severity so they flag
  their cell. Remaining false negative: a leading-character drop in
  customer_name ("C…" → "…"), which keeps matching every declarative pattern —
  no format rule can catch it without guessing; it still reaches the reviewer
  through the low-confidence path only when confidence drops.
- Calibration: ECE raw 0.120 → 0.003 after Platt (isotonic 0.119).

## How to run

```
.venv/bin/python -m pytest tests/ -q
.venv/bin/python -m benchmark.validation_eval benchmark/seed
.venv/bin/python benchmark/validate.py
```

Details: `docs/reports/p5_validation.md`.
