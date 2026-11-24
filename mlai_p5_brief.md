# P5 brief — Validation & confidence (mlai, LV3)

## Context
Working dir on THIS machine: `/root/image-extraction-engine`.
P0–P4 are done and audit fixes A+B are pushed (HEAD 842592d). This phase
builds the extraction-and-validation layer. Core principle (standing):
low-confidence or ambiguous values must be flagged for review, NEVER
silently guessed; AI output is a proposal, never truth.
Build on what exists: `validate_value` / `format_regex` is already wired
into extraction (audit-fix B item 3) and `needs_review` already escalates
the run status to `NEEDS_REVIEW` (audit-fix B item 4) — reuse them, do
not redo them.

## Scope
In scope: normalization, Pydantic validation, domain rule engine,
confidence aggregation + calibration, anomaly flags, review-queue data
model + correction API (library level), audit trail.
Out of scope: the web review UI (P7 — this phase exposes the backend
functions and data model the UI will use), exports (P6).

## Tasks (in order)
1. `engine/validation/normalize.py` — field normalization:
   Unicode NFC, whitespace cleanup, locale-aware numbers (Vietnamese
   `1.234,5` vs English `1,234.5`, configurable per profile), dates,
   unit canonicalization (`t` ↔ `kg`, `mm` ↔ `m`) that KEEPS the
   original unit. Keep `raw_text` alongside the normalized value.
2. Dynamic Pydantic schemas — generate validation models from P4 profile
   field definitions + P0 schemas: required fields, types, regex formats
   (e.g. coil ID pattern), enums for states.
3. Domain rule engine (`engine/validation/rules.py` + YAML rule files):
   declarative rules with ID, severity (error/warning/info), message:
   ranges (e.g. THICK plausible range), cross-field consistency (e.g.
   weight ≈ f(thickness, width, length, density) within tolerance),
   uniqueness of coil IDs within a table, checksum/format rules,
   row-count consistency, units matching their columns. Rules and
   thresholds configurable per profile WITHOUT code changes.
4. Confidence model (`engine/validation/confidence.py`): combine OCR
   token confidence, multi-scale/ensemble agreement, table-cell
   confidence, rule results and image-quality signals into a 0–1 field
   confidence; aggregate up to table and document level. Calibrate on
   the benchmark dev split (isotonic or Platt) and report a reliability
   diagram + ECE (expected calibration error) on the test split.
   NOTE: scikit-learn is NOT installed in the venv — implement
   calibration with numpy/scipy only (scipy 1.18.1 IS installed). Do NOT
   install any package.
5. Ambiguity handling: confusable characters with OCR alternatives — try
   candidates against format rules. Exactly one passes → propose it with
   `needs_review=true` and record the reason. Zero or several pass →
   flag the field, do NOT choose. Missing values stay null with a reason,
   NEVER imputed.
6. Anomaly flags: outliers against the table's column distribution,
   duplicate rows, unit mismatches, impossible values, vision-model
   output contradicting OCR.
7. Review backend (`engine/validation/review.py`): `ReviewItem` model
   (field ref, value, alternatives, confidence, reasons, crop/bbox for
   display); functions to list pending items, accept / correct / reject a
   value, and re-run validation after edits. Configurable thresholds per
   field and profile decide auto-accept vs review.
8. Audit trail (`engine/validation/audit.py`): immutable log of every
   correction (who, when, old value, new value, reason); corrected
   results versioned; persist to files by default, with a repository
   interface ready for PostgreSQL later.
9. Integration: provide a `validate_result(result, profile)` entry point
   and wire it into the industrial pipeline's final step (additive — do
   not break the existing extraction flow). Every field and cell gets
   `confidence`, `needs_review`, `validation_results[]`, `warnings[]`;
   `extraction_status` becomes one of completed,
   completed_with_warnings, needs_review, failed.
10. Evaluation: report the share of real errors caught (flagged) vs false
    alarms, field-level accuracy after auto-accept, review rate at
    different thresholds, and ECE — on the benchmark seed set with known
    wrong values injected (document how the wrong values were made).
    Target: error-catch recall ≥ 95% with the review rate reported.
11. Docs: `docs/reports/p5_validation.md` covering calibration and the
    threshold trade-offs. Write `P5_REPORT.md` (what was built, numbers,
    checks) then stop.

## Checks (run before stopping)
`.venv/bin/python -m pytest tests/ -q`,
`.venv/bin/python benchmark/validate.py`,
`ruff check engine benchmark tests`, `mypy engine` — all must pass.
Record results in `P5_REPORT.md`. Do NOT create files under `tests/` in
this run (a separate test run follows).

## Standing rules (do not break)
- Add-only to shared files; never rewrite a shared file from scratch.
- NEVER `rm -rf` anything. NEVER delete files.
- NEVER deploy, commit or push — the liaison does that.
- NEVER install packages (apt/pip/uv) — the liaison installs what you need.
  If a package is missing, STOP and write it into `BLOCKED.md`.
- If you get stuck: STOP. Write the blocker and exactly what you need
  into `BLOCKED.md` in the project dir, then stop the run. Do NOT guess,
  do NOT work around it silently, do NOT skip ahead to P6.
