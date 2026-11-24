# P0 Implementation Report

Date: 2026-11-24 · Prompt set: `prompts_aws_quick.md` · Plan: `plan.md`

## What was delivered (P0 scope only)

- **Unified output schema** — `engine/schema/models.py`: Pydantic v2 model
  `ExtractionResult` matching the plan's unified data model (document_type,
  extraction_status, source, pages, text_blocks with language + per-block
  confidence, tables, fields, validation_results, warnings, exports,
  processing timings, namespaced `extensions`). The plan's own example
  validates unchanged. `export_json_schema()` exports draft 2020-12 JSON
  Schema; the current export is saved at `docs/spec/schema_v0.json`.
- **Taxonomy with registration mechanism** — `engine/schema/taxonomy.py`:
  17 default categories (11 general, 5 industrial, 1 fallback) and
  `register_category()`; new categories extend the system without pipeline
  rewrites. Covered by tests.
- **Industrial field dictionary** — `engine/schema/industrial_fields.py`:
  ZONE, HOT_COIL_NO, COLD_COIL_NO, THICK, WIDTH, WEIGHT, LENGTH,
  PRODUCT_CODE with types, units, format regexes, plausible ranges and a
  `validate_value()` checker. Factory-specific values are marked
  configurable for P4 profiles.
- **Metric definitions + reference implementations** — `docs/spec/metrics.md`
  (exact formulas and normalization rules) and `engine/metrics.py`
  (CER, WER, table structure accuracy as cell-adjacency F1, field accuracy,
  coil-ID exact-match accuracy, processing-time stats). All unit-tested.
- **Spec documents** — `docs/spec/`: `inputs.md` (formats, limits, color
  modes, typed error policy, categories, Vietnamese-diacritics requirement),
  `privacy.md` (local-only default; external APIs strictly opt-in),
  `priorities.md` (P0–P3 mapping), `open_questions.md` (8 questions for
  sign-off), `metrics.md`.
- **Benchmark seed set** — `benchmark/`: 7 required content classes x 5
  samples = 35 samples under `benchmark/seed/` (placeholder images +
  schema-valid ground truth), `benchmark/tools/generate_seed.py`,
  `benchmark/validate.py` (schema, taxonomy and image-existence checks;
  exits non-zero on error).
- **CI** — `.github/workflows/ci.yml`: ruff, mypy, pytest and the seed
  validator on every PR/push, least-privilege permissions, pip caching.
- **Service skeleton** — `service/README.md` describing the planned FastAPI
  boundary (implementation is P7, not started).
- Stub packages for later phases (`engine/router`, `engine/preprocessing`,
  `engine/general`, `engine/industrial`, `engine/tables`,
  `engine/validation`, `engine/export`) are in place, empty by design.

## Step log (per the brief's execution-contract section)

| Step | Result |
|---|---|
| Skeleton (pyproject, packages, CI) | SUCCESS |
| Schema models + JSON Schema export | SUCCESS (6,418-byte schema exported) |
| Taxonomy + registration mechanism | SUCCESS |
| Industrial field dictionary | SUCCESS |
| Spec documents (5 files) | SUCCESS |
| Seed set generation | SUCCESS (35 samples, 7 categories) |
| Seed validator run | SUCCESS ("35 passed, 0 failed") |
| Unit tests | SUCCESS (41 passed in 0.17s) |
| ruff | SUCCESS ("All checks passed!") |
| mypy engine | SUCCESS ("no issues found in 13 source files") |

Failures encountered and fixed during the run (all verified green
afterwards): seed-generator undefined variable (`i` → `index`), validator
glob missing one directory level, PRODUCT_CODE regex rejecting the
documented `x` dimension separator, missing `$schema` key in the pydantic
JSON Schema export, and lint/type nits.

Not done (intentionally, out of P0 scope): OCR/vision backends, table
detection model, XLSX export, router classifier, FastAPI service, web UI —
these belong to P1–P8.

## Open items needing stakeholder input

See `docs/spec/open_questions.md` (input limits, coil-ID formats, language
scope, external-API policy, retention defaults, real ground-truth images,
TEDS vs adjacency F1).

## Notes on limits

Placeholder seed images are 1x1 PNGs; ground truth is real and
schema-valid. Real images replace them in P1+ without format changes.
Default input limits (50 MB, 8000x8000, 100 pages, 50 files/batch) are
documented proposals pending confirmation.
