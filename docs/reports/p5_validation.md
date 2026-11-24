# P5 — Validation & Confidence

## Modules (engine/validation/)

| Module | Responsibility |
| --- | --- |
| `normalize.py` | Unicode NFC + whitespace collapse, locale-aware numbers (`1,234.56` and `1.234,56`), dates to ISO, unit canonicalization (mm→m, t→kg). `LocaleConfig` is per-factory, set from the profile/locale name — no code change for a new factory. Raw text is always kept on `NormalizedValue`. |
| `dynamic_schema.py` | Builds a concrete Pydantic model from a profile's field definitions: required, type, `format_regex` (coil-ID pattern), min/max ranges, enum choices. Failures become `ValidationIssue`s with IDs and severities, never exceptions. |
| `rules.py` + `rules/*.yaml` | Declarative rule engine. Rules are YAML: `default.yaml` plus optional `<profile>.yaml` (a profile rule with the same ID replaces the default, so thresholds are tunable per factory). Types: `range`, `format`, `cross_field` (safe arithmetic AST, e.g. weight ≈ thick × width × length × steel density), `uniqueness`, `row_count`, `unit_match`. Findings carry field/table/row/col position. |
| `confidence.py` | Weighted signal combination (OCR/cell confidence, image quality, rule outcome, cross-check agreement) with error/warning decay; rollups cell → table → document. Calibration: Platt (logistic) and isotonic (PAVA), plus ECE and reliability-diagram bins. numpy-only. |
| `ambiguity.py` | Confusable-character handling (O/0, I/1, S/5, B/8, Z/2, 6/G). When a reading fails its format rules, candidates are enumerated and tested; exactly one passing candidate → `proposed` (never auto-applied), zero or several → `ambiguous`. |
| `anomalies.py` | Statistical column outliers (median + MAD), duplicate rows, unit mismatches vs the profile, impossible values, vision-vs-OCR contradictions. |
| `review.py` | Review queue for flagged fields/cells. Actions: accept / correct / reject, JSON persistence, per-field/per-profile thresholds from `ReviewThresholds`. |
| `audit.py` | Append-only JSONL audit trail of every decision; corrected results are versioned as immutable JSON files (`ResultVersionStore`). |
| `validate_result.py` | Orchestrates all of the above over one `ExtractionResult` and writes confidences, `needs_review`, `validation_results`, review items and `extensions["validation"]` (document confidence, finding counts, review IDs) back. |

## Pipeline wiring

`IndustrialVision.__init__` accepts `review_thresholds`, `review_backend` and an
optional `quality_hook` (image → [0,1]). `IndustrialVision.process` runs
`validate_result` on the final result; status becomes `needs_review` or
`completed_with_warnings` accordingly.

## Evaluation (benchmark/validation_eval.py)

Controlled OCR-like errors of three kinds (confusable swap, transposition of
two adjacent characters, dropped digit in a numeric value, 25 % of positions,
fixed RNG seed) are injected into the 35 ground-truth results of the seed set;
`validate_result` runs with `profile_name="steel_coil_mill"`, and findings that
point at an injected-error position count as true positives. Confidence is
scored per field/cell (not just per document) and calibrated on a held-out
half of the results. A second, synthesized layout renames tables, columns and
fields to names the seed rules do not know, so the report shows how much
recall depends on the seed vocabulary. Results (`benchmark/results_validation.json`,
24/11 fix round): seed layout precision 1.000, recall 0.667, F1 0.800
(per-kind recall: confusable 1.000, transposition 0.417, digit_drop 0.750);
renamed layout recall 0.000 — a deployment must ship its own profile YAML.
Raw ECE 0.214 (seed) improves to 0.083 after Platt calibration fitted on the
held-in half and scored on the held-out half.

## Tests

`tests/test_validation.py` is specified to cover the fix round: the formula
sandbox accepting comparison operators, duplicate rule-id warnings, two-digit
thousands grouping flagged as ambiguous, ambiguity proposals flowing through
`validate_result` (proposals on the field + `extensions["validation"]["ambiguity"]`),
error kinds landing on both fields and cells under a profile name, and review
items for needs_review cells. NOTE (24/11 fix round): the file itself could
not be created in that round (workspace guard denied new test files); the
existing suite (80 tests) still passes and covers normalization, rule types,
ambiguity, confidence and the review backend indirectly.

Fix round wiring note: `validate_result` now really runs normalization →
dynamic profile schema → declarative rules → ambiguity; normalization writes
cleaned values back in place, ambiguous groupings become `NORMALIZE_AMBIGUOUS`
warnings, and confusable readings become `AMBIGUITY_PROPOSED` (warning) /
`AMBIGUOUS_VALUE` (error) findings with `proposals` on the field/cell and an
`extensions["validation"]["ambiguity"]` summary. Cell accept thresholds now
honor per-column keys (`table.column`, `profile.table.column`), and only
error-severity findings count as a rule failure for the confidence penalty.
