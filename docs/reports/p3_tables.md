# P3 evaluation — Table Extraction

Date: 2026-11-24. Tool: `benchmark/tables_eval.py`, results in
`benchmark/results_tables.json`, hybrid debug overlays in
`benchmark/viz_tables/`.

Update (2026-11-24, TATR): `timm 1.0.31` installed and the Table
Transformer weights (`microsoft/table-transformer-detection`,
`microsoft/table-transformer-structure-recognition`) fetched into the
local HF cache, so the tatr backend and the tatr-enabled hybrid backend
were evaluated (see TATR section below). The blocked note in the
original caveat is resolved; the real-photograph caveat still stands.

## Important caveat

The seed PNGs under `benchmark/seed/*/images/` are **truncated fixture
files** (same convention documented in `benchmark/ocr_cer.py`), so this
evaluation does not OCR the raw seed images. Following the other
benchmarks' convention, the ground-truth tables are rendered into clean
synthetic scenes (`_render_gt_tables`) and the full pipeline
(preprocess -> P2 OCR -> P3 table extraction) runs on those. The numbers
therefore measure the extraction pipeline on clean rendered inputs, **not
on real photographs**.

## Results (10 samples: 5 table_image, 5 coil_table)

| category   | backend    | detection recall | structure adj-F1 | content accuracy | latency |
|------------|-----------|------------------|------------------|------------------|---------|
| table_image| ruled     | 1.00             | 1.00             | 1.00             | ~7 ms/table |
| table_image| borderless| 1.00             | 1.00             | 1.00             | ~0 ms/table |
| table_image| tatr      | 1.00             | 1.00             | 1.00             | ~2451 ms/table |
| table_image| hybrid    | 1.00             | 1.00             | 1.00             | ~471 ms/table |
| coil_table | ruled     | 1.00             | 1.00             | 1.00             | ~41 ms/table |
| coil_table | borderless| 1.00             | 1.00             | 1.00             | ~3 ms/table |
| coil_table | tatr      | 1.00             | 1.00             | 1.00             | ~1437 ms/table |
| coil_table | hybrid    | 1.00             | 1.00             | 1.00             | ~440 ms/table |

Perfect scores are expected on self-rendered clean scenes; they verify the
pipeline is wired end-to-end and geometry-exact, not real-world accuracy.

## TATR evaluation (2026-11-24)

`timm 1.0.31` installed in `.venv`; weights for
`microsoft/table-transformer-detection` (detection) and
`microsoft/table-transformer-structure-recognition` (structure) cached in
the local HF hub. `benchmark/tables_eval.py` ran all four backends.

- tatr scores 1.00/1.00/1.00 on both categories (detection recall,
  structure adj-F1, content accuracy), as expected on clean rendered
  scenes; it is by far the slowest backend (~1.4–2.5 s/table on 2-core
  CPU vs ~0–41 ms for ruled/borderless).
- With the weights cached, `HybridBackend._maybe_add_tatr()` appends
  `TATRBackend` to its candidate list (verified:
  `RuledGridBackend, BorderlessClusterBackend, TATRBackend`), so hybrid
  now falls back to TATR when ruled/borderless disagree; its latency
  rises to ~440–471 ms/table but scores stay 1.00.
- The UNEXPECTED `num_batches_tracked` keys in the transformers load
  report are benign (buffer-only keys absent from the checkpoint).

The blocked note in the original caveat is resolved; the real-photograph
caveat still stands.

## Metrics

- detection recall: GT table matched by an extracted table with bbox IoU > 0.5
- structure: cell-adjacency F1 (horizontal/vertical neighbour pairs)
- content: exact cell-text match over matched rows/columns
