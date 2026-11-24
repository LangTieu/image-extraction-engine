# Benchmark (P0 seed)

Structure:

    benchmark/seed/<category>/images/<name>.png            # input image
    benchmark/seed/<category>/ground_truth/<name>.json     # expected output (unified schema)
    benchmark/seed/<category>/README.md                    # category notes

The seed set covers the P0-required content classes at 5 samples each:
photographed documents (`photo_document`), structured forms (`form`), dense
small-font tables (`table_image`), desktop (`screenshot_desktop`) and mobile
(`screenshot_mobile`) screenshots, angled PLC/HMI photos (`industrial_hmi`)
and coil tables (`coil_table`).

Images in the seed set are small synthetic placeholders; ground truth is
real, schema-valid JSON. Replace the placeholder images with real samples in
P1+ — the layout and ground-truth format do not change.

## Usage

    python -m benchmark.tools.generate_seed [dir]   # (re)generate the seed set
    python -m benchmark.validate [dir]              # validate ground truth vs schema

The validator checks every ground-truth file against the unified schema,
verifies the `document_type` is a registered category, and confirms each
referenced image exists. It exits non-zero on any error, so CI runs it
directly.

Later phases add: scoring (`benchmark/score.py`, P8), perturbation sets
(P5), and per-variant timing comparisons.
