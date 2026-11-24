# Brief for ML AI Code — Implement P0 only (Quick prompt set)

## Context

You compared both prompt sets and chose `prompts_aws_quick.md` (verdict in
`COMPARISON.md`). Now implement phase P0 of that set, in this directory
(`/data/home/image-extraction-engine`).

## Task — implement P0 ONLY

Read the P0 prompt in `prompts_aws_quick.md` ("P0: Requirements & Data
Specification") and implement it exactly:

- Repository skeleton: `engine/` (`router/`, `preprocessing/`, `general/`,
  `industrial/`, `tables/`, `validation/`, `export/`), `service/`,
  `benchmark/`, `docs/`, `tests/`; `pyproject.toml` (Python 3.11+),
  ruff, mypy, pytest, basic CI config.
- Input specification (`docs/spec/inputs.md`), content-category taxonomy with
  a registration mechanism.
- Unified output schema (`engine/schema/`): Pydantic v2 models + exported
  JSON Schema, validating the plan's example payload.
- Industrial field dictionary (coil fields with types, units, format, ranges).
- Language requirements (Vietnamese + English), privacy/security constraints
  (local-only by default).
- Benchmark dataset spec (`benchmark/README.md`) + folder layout + ground-truth
  format + labeling guidelines + seed samples (~5 per category, synthetic
  placeholders OK) + validator script; every seed file must pass the validator.
- Metric definitions (`docs/spec/metrics.md`) with formulas + reference
  implementation stubs with unit tests.
- Priorities mapped to MVP/later; open questions in `docs/spec/open_questions.md`.

Do NOT start P1–P8. Do NOT change anything outside this directory.

## Rules

- NEVER run `rm -rf` or delete files outside this directory.
- After writing code, run the tests / validation yourself (pytest, validator
  on seed files, schema import + JSON Schema export) and report the exact
  exit codes and outputs. Every claim of success must come with the exact
  command output that proves it. Never invent a URL, ID, path, or output value.
- If a step fails, report it as failed with the error text. Do not report a
  failed step as success.
- When P0 is done, stop and write `P0_REPORT.md`: file list created/changed,
  test/validation results with exit codes, and anything left open.
- Do not commit, push, or deploy anything.
