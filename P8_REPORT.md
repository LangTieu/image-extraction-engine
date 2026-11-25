# P8 Report — benchmark harness, smoke run, verification

Branch `p8-review` (main HEAD `2086dab`), date 2026-11-25.
Detailed benchmark write-up: `docs/reports/benchmark_report.md` and
`docs/reports/p8_benchmark.md`. Raw artifact: `benchmark/artifacts/smoke_2086dab8/`
(config.json, metrics.json, errors.json, robustness.json, performance.json,
reports/*.png) plus the one-variant `smoke_charts_only_2086dab8/`.

## What P8 delivered

- Benchmark harness `benchmark/run.py`: variants, CER/WER (jiwer), field accuracy
  with bootstrap CI, routing accuracy, table-structure scoring, robustness
  perturbations, performance timing, gates, error analysis with next-steps groups.
- Seed validation (`benchmark/validate`): **35/35 pass**.
- Smoke run committed as a real artifact (4 variants × 10 quick-subset samples).
- CI: `ci.yml` now runs ruff, `mypy engine benchmark service tests`, pytest,
  seed validation and `python -m benchmark.run --quick --tag ci`.
- Docs: three reports (this file, `docs/reports/p8_benchmark.md`,
  `docs/reports/benchmark_report.md`).

## Verification (all run bare, exit codes read)

| check | command | result |
| --- | --- | --- |
| unit tests | `.venv/bin/python -m pytest -q` | exit 0, no FAILED lines |
| seed validation | `.venv/bin/python -m benchmark.validate` | exit 0 — "35 passed, 0 failed" |
| lint | `.venv/bin/python -m ruff check .` | exit 0 — "All checks passed!" |
| type check | `.venv/bin/python -m mypy engine benchmark` | exit 0 — "Success: no issues found in 75 source files" |
| industrial eval | `.venv/bin/python -m benchmark.industrial_eval` | exit 0 — routing 1.000, field F1 0.933, unit acc 0.875, unknown-flag 1.000 |
| validation eval | `.venv/bin/python -m benchmark.validation_eval` | exit 0 — 35 results, error_rate 0.25, review_rate 0.16 |

## Key smoke numbers (quick subset, 10 industrial placeholder samples)

- default_tesseract: route 0.500, field 0.500, CER 1.000 → CER gate **FAIL**
  (expected: tesseract reads none of the synthetic placeholder text).
- ocr_paddle / ocr_ensemble: route 1.000, field 0.938, CER 0.607 (still above
  the 0.6 gate).
- Performance (default, `smoke_2086dab8/performance.json`): mean 2973 ms/img,
  p95 5477 ms, 0.336 img/s on 2 CPUs. Paddle variants ≈ 10× slower on the
  quick subset (model load dominates 10 images).
- Robustness: not run in smoke (`robustness.json` = `{"skipped": true}`) —
  quick mode skips perturbations. **Chưa đo.**
- Error analysis: 5 routing mismatches (all coil_table → industrial_hmi),
  40 field_missing, 0 field_wrong, 0 field_extra, 0 table_structure scored,
  10/10 high CER.

## Honesty notes (challenges from earlier rounds, resolved or stated)

- `benchmark/run.py:253` `# type: ignore[assignment]` was **removed and fixed at
  the root** this round: `analyze_errors` now narrows with
  `assert isinstance(samples_obj, list)` (same idiom as the rest of the file)
  before assigning to `list[dict[str, object]]`. mypy passes without the
  suppression. Three unrelated `# type: ignore[arg-type]` remain on
  `PipelineVariant(...).build()` calls (lines 86/177/211) — different issue
  (kwargs expansion of a TypedDict), not fixed in P8.
- The baseline run before the harness fixes was stopped by a time limit — any
  comparison against it is **partial**, not a full baseline comparison.
- Performance numbers differ between the two smoke artifacts for the same
  variant (2322 ms vs 2973 ms mean) — single small runs on a shared 2-CPU
  box; treat timings as rough.
- The chart PNGs in the artifact were never opened this round; all statements
  here come from the JSON files.

## Not run / not measured (chưa đo — không bịa)

- **Robustness curves** (blur/jpeg/scale/affine severity 0–3): quick smoke
  skips perturbations; a full run is needed.
- **Qwen2.5-VL local**: not-run — this machine (LV3) lacks RAM/disk.
- **Gemini Vision**: off — no API key configured.
- **Full 35-sample run of all variants**: only the 10-sample industrial quick
  subset ran end-to-end; the seed set itself validates 35/35.
- **Real-image evaluation**: seed renders scenes from seed JSON at run time
  (1×1 placeholder images), not real photographs — absolute accuracy numbers
  are not production-meaningful; the harness, metrics, gates and artifact
  pipeline are the deliverable.

## Conclusion

P8 scope is complete: harness + gates + CI wiring are green, the smoke artifact
is real and committed, and all six verification checks exit 0. The known red
(CER gate fails on placeholders with tesseract) is a dataset/OCR-reality
finding, not a broken gate. Next phases should run the full 35-sample suite
with real scans and enable robustness curves.
