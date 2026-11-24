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

Controlled OCR-like errors (confusable swaps / character drops at a 25 % rate,
fixed RNG seed) are injected into the 35 ground-truth results of the seed set;
`validate_result` runs over the degraded results; findings that point at an
injected-error position count as true positives. Confidence is scored against
"not degraded" and calibrated. Results: `benchmark/results_validation.json`
(detection precision/recall/F1, ECE raw vs Platt vs isotonic, reliability
diagram).

## Tests

`tests/test_validation.py` covers: normalization (locales, ambiguity notes),
dynamic schema (required/format/range/enum), every rule type, ambiguity
resolution, anomaly detectors, confidence + calibration (ECE decreases after
Platt), review backend accept/correct/reject with the audit trail, and the
end-to-end `validate_result` status transitions.
