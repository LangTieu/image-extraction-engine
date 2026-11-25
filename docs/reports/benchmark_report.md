# Benchmark Report — full write-up (P8)

Branch `p8-review`, repo HEAD at run time `2086dab`, date 2026-11-25.
Primary artifact: `benchmark/artifacts/smoke_2086dab8/` (all four variants);
secondary one-variant artifact `benchmark/artifacts/smoke_charts_only_2086dab8/`.

## 1. What was run

```
.venv/bin/python -m benchmark.run --quick --tag smoke          # 4 variants
.venv/bin/python -m benchmark.validate                          # seed check
.venv/bin/python -m benchmark.industrial_eval                   # routing/F1
.venv/bin/python -m benchmark.validation_eval                   # error/review rates
```

- Seed: `benchmark/seed/`, **35 samples across 7 categories**, split seed 42.
- The `--quick` smoke subset is the **10 industrial samples** (`coil_table`,
  `industrial_hmi`, 5 each).
- Images are **rendered at run time from the seed JSON** (1×1 placeholder
  pixels), not real photographs. All absolute numbers reflect that.
- Variants: `default_tesseract`, `ocr_paddle`, `ocr_ensemble`, `no_preprocess`.

## 2. Seed validation

`benchmark.validate`: **35 passed, 0 failed** (exit 0). Duplicate rule-id
warnings (`COIL_ID_FORMAT`, `WEIGHT_UNIT` redefined by `steel_coil_mill.yaml`,
later definition wins) are expected overrides, not errors.

## 3. Smoke metrics (quick subset)

Source: `smoke_2086dab8/metrics.json`.

| variant | n | route_acc | field_acc | coil_id_acc | CER | WER |
| --- | --- | --- | --- | --- | --- | --- |
| default_tesseract | 10 | 0.500 | 0.500 | 0.500 | 1.000 | 1.000 |
| ocr_paddle | 10 | 1.000 | 0.938 | — | 0.607 | — |
| ocr_ensemble | 10 | 1.000 | 0.938 | — | 0.607 | — |
| no_preprocess | 10 | 0.500 | 0.500 | — | 1.000 | — |

- field_accuracy 95% bootstrap CI (default variant): point 0.500,
  CI [0.20, 0.80] — 10 samples give a very wide interval by construction.
- `table_structure_f1`: None for these samples (no table regions detected on
  placeholders) — **chưa đo**, not a zero.
- Per category (default_tesseract): coil_table route 0.000 / field 0.000 /
  CER 1.000; industrial_hmi route 1.000 / field 1.000 / CER 1.000.

## 4. Gates

`benchmark.run --gates` on the default variant: **FAIL** — `cer=1.000 > 0.6`.
Expected on placeholder images with tesseract (CER 1.0 = zero character
overlap). Paddle variants reach CER 0.607, still marginally above the 0.6
gate. The gate mechanism itself works; the dataset/OCR pairing does not.

## 5. Performance

Source: `smoke_2086dab8/performance.json` (default_tesseract, 10 images,
2-CPU container):

- mean **2973 ms/img**, p95 **5477 ms**, batch 29.7 s, throughput **0.336 img/s**.
- Paddle-based variants are ≈10× slower per image on the quick subset
  (model load dominates 10 images): 243 s wall for 10 images in the
  charts-only run.
- The charts-only artifact measured the same default variant at mean 2322 ms /
  p95 4033 ms / 0.431 img/s. Run-to-run spread on a shared 2-CPU box is large;
  treat timings as order-of-magnitude only.

## 6. Robustness

`robustness.json` = `{"skipped": true}` — quick mode skips perturbations.
Severity 0–3 curves (blur, jpeg, scale-down, affine) and per-perturbation
breakdown severity are implemented in the harness but **not measured** in this
run (chưa đo). Requires a full (non-`--quick`) run.

## 7. Error analysis

Source: `smoke_2086dab8/errors.json` (default_tesseract):

| group | count | detail |
| --- | --- | --- |
| routing_mismatch | 5 | all coil_table samples routed to industrial_hmi |
| field_missing | 40 | downstream of routing + OCR failure |
| field_wrong | 0 | fields found on HMI were correct |
| field_extra | 0 | — |
| table_structure | 0 | no samples scored |
| high_cer (> 0.3) | 10/10 | OCR reads no text on placeholders |

Interpretation: coil_table failures are routing-level (wrong profile →
everything missing); industrial_hmi failures are OCR-level (tesseract extracts
no usable text from the placeholder rendering). `NEXT_STEPS` per group is
written into `errors.json`.

## 8. Independent evals (verification battery)

- **Industrial eval** (`benchmark.industrial_eval`, exit 0): routing 1.000,
  field F1 0.933, unit accuracy 0.875, unknown-rate flag 1.000.
- **Validation eval** (`benchmark.validation_eval`, exit 0): 35 results,
  error_rate 0.25, review_rate 0.16 (n_positions 100, seed 42).
- Both evals operate on the seed's ground-truth JSON, so they measure the
  field/routing logic, independent of the placeholder-image OCR ceiling.

## 9. Limitations and honesty notes

- **Placeholder images only.** The seed renders scenes from JSON at run time;
  there are no real scans in this run. Absolute accuracy/CER numbers are a
  harness sanity check, not a capability estimate.
- **Baseline comparison is partial.** The pre-fix baseline run was stopped by
  a time limit, so only the portion it completed can be compared.
- **Qwen2.5-VL local**: not-run — this machine lacks RAM/disk.
- **Gemini Vision**: off — no API key.
- **Robustness**: implemented, not measured (see §6).
- **Timing noise**: see §5, two artifacts disagree by ~25% on mean latency.
- Chart PNGs in the artifact were never visually opened; this report uses only
  the JSON files (`metrics.json`, `performance.json`, `errors.json`,
  `robustness.json`, `config.json`).

## 10. Conclusion

The P8 benchmark harness is functional and verified: seed validates 35/35,
all four smoke variants complete and produce metrics/gates/error analysis, and
the two independent evals confirm routing 1.000 / field F1 0.933 on the
logic level. The CER gate fails as expected on placeholder text. The next
meaningful measurement requires real scanned images, a full 35-sample run of
all variants, and robustness curves.
