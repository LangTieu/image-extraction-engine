# P8 Benchmark Report (smoke run)

Branch `p8-review`, seed `2086dab8`, date 2026-11-25.
Artifacts: `benchmark/artifacts/smoke_charts_only_2086dab8/` (config, metrics.json,
errors.json, robustness.json, performance.json, reports/*.png) and
`benchmark/artifacts/smoke_2086dab8/` (all four variants).

## Setup

- Seed set: `benchmark/seed/` (35 samples across 7 categories). The `--quick`
  smoke subset runs the 10 industrial samples (`coil_table`, `industrial_hmi`,
  5 each) against the placeholder images.
- Runner: `python -m benchmark.run --quick --tag smoke`; variants:
  `default_tesseract`, `ocr_paddle`, `ocr_ensemble`, `no_preprocess`.

## Results (quick subset, default_tesseract vs OCR variants)

| variant | n | route_acc | field_acc | coil_id_acc | CER | WER |
| --- | --- | --- | --- | --- | --- | --- |
| default_tesseract | 10 | 0.500 | 0.500 | 0.500 | 1.000 | 1.000 |
| ocr_paddle | 10 | 1.000 | 0.938 | — | 0.607 | — |
| ocr_ensemble | 10 | 1.000 | 0.938 | — | 0.607 | — |
| no_preprocess | 10 | 0.500 | 0.500 | — | 1.000 | — |

field_accuracy 95% bootstrap CI (default, quick subset): point 0.500, CI [0.20, 0.80]
(10 samples — far too narrow a set for a tight interval).

Per category (default_tesseract):

| category | n | route | field | CER | mean ms |
| --- | --- | --- | --- | --- | --- |
| coil_table | 5 | 0.000 | 0.000 | 1.000 | 778 |
| industrial_hmi | 5 | 1.000 | 1.000 | 1.000 | 4009 |

## Gates

`--gates` (primary gates on the default variant): **FAIL** — `cer=1.000 > 0.6`.
The tesseract path reads none of the synthetic placeholder text correctly
(CER 1.0 means no character overlap), so the gate fails as expected on this
dataset. Paddle-based variants pass the CER direction at 0.607 but still above
the 0.6 gate.

## Performance (default_tesseract, quick subset, 2-CPU container)

- mean 2322 ms/image, p95 4033 ms, throughput 0.43 img/s (single-threaded pipeline).
- The paddle variants take ~10x longer per image (model load dominates the
  quick subset: 243 s wall for 10 images).

## Error analysis (default_tesseract, quick subset)

- routing_mismatch: 5 (all coil_table — routed to the wrong profile)
- field_missing: 40
- field_wrong: 0 (when a field is found on HMI it is correct)
- field_extra: 0
- table_structure (f1 < 0.5): 0 samples scored
- high_cer (> 0.3): 10 of 10

Interpretation: tesseract on the placeholder images extracts essentially no
usable text; the coil_table failures are routing-level (wrong profile → all
fields missing), the HMI failures are OCR-level. Next-step guidance per group
is written into `errors.json` (`NEXT_STEPS`).

## Robustness

Quick mode skips perturbations (`robustness.json` = `{"skipped": true}`); the
full run records severity 0–3 curves for blur, jpeg, scale-down and affine and
derives a breakdown severity per perturbation.

## Known limitations

- Seed images are synthetic placeholders; absolute numbers are not meaningful
  for production planning, but the harness, metrics, gates and artifacts are.
- `table_structure_f1` is None for these samples (no table regions detected by
  the default variant on placeholders).
- Duplicate rule-id warnings from `steel_coil_mill.yaml` overrides are expected
  (later definitions win) but are noisy; worth deduplicating in a later phase.
