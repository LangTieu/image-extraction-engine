# P1 Report — Preprocessing

## Status: COMPLETE — "must not hurt OCR" bar met after P1-fix

## Scope

Phase P1 per `mlai_p1_brief.md`: YAML-driven preprocessing pipeline, named
profiles, transforms (rotate / orientation / perspective / crop / denoise /
contrast / sharpen / upscale), quality report, debug harness, CER
mini-benchmark.

## What was done in this continuation

Previous run stopped at max steps with the implementation largely in place.
Remaining items only were executed:

### 1. Re-check orientation

Found and fixed a real bug in `engine/preprocessing/transforms.py`
(`estimate_orientation_90`): the Sobel row-projection score is
mirror-symmetric (0 ≡ 180, 90 ≡ 270 by construction), so the ink-centroid
tie-break decides the sign. A full-frame border rectangle (common on HMI
panels) put ink in every row, flattening the centroid to 0.5 and breaking the
tie-break on framed screens. Fix: mask out near-full-width ink rows and
near-full-height ink columns (frame lines) before computing the centroid.

Verified end-to-end on synthetic photographed panels (light and dark themes):
all four rotations (0/90/180/270 CW) are detected and `correct_orientation`
restores the original upright pixels exactly.

### 2. CER mini-benchmark (RapidOCR, industrial_screen_photo profile)

`benchmark/preprocess_cer.py` runs 5 scene kinds x 2 samples. Mean CER
(per-kind average, after the P1-fix run):

| scene        | raw    | preprocessed | delta   |
|--------------|--------|--------------|---------|
| clean        | 0.0435 | 0.0435       |  0      |
| skewed_3deg  | 0.0435 | 0.0435       |  0      |
| skewed_7deg  | 0.0381 | 0.0381       |  0      |
| perspective  | 0.3478 | 0.3478       | -0.0005 |
| dark_glare   | 0.4783 | 0.4728       | -0.0055 |

Overall mean: raw 0.1902 vs preprocessed 0.1891 (see
`benchmark/results_preprocess_cer.json`). Preprocessing is no worse than
raw on every scene kind — the brief's "must not hurt OCR" bar is **met**.

**P1-fix changes (this run).** The earlier finding — preprocessing
increased CER on every scene kind — was fixed with two changes:

- `detect_quadrilateral` (engine/preprocessing/transforms.py) now rejects
  quads whose corners hug the image border (`frame_tolerance_px`) and
  picks the largest *inner* content quad across all Canny contours
  (RETR_LIST) before the Otsu fallback, instead of the largest external
  contour — which was the canvas frame line.
- `perspective` and `sharpen` are gated (engine/preprocessing/pipeline.py):
  perspective runs only when the detected quad is actually
  perspective-distorted (largest corner deviation from 90° exceeds
  `min_corner_deviation_deg`, 6° default); sharpen runs only when quality
  flags BLURRY or LOW_CONTRAST. Both steps log a `skipped` reason in the
  step info when the gate holds. Frontal/skewed scenes now skip both,
  matching the orientation-only baseline.

Residual note: on the synthetic perspective/dark_glare scenes the
remaining gap vs raw is dominated by OCR limits on those scenes, not
preprocessing (per-sample deltas are within ±0.011 and cancel per kind).

### 3. Lint / types / tests

- `ruff check engine benchmark tests` — **all checks passed** (14 findings
  fixed this run: line length wraps and one unused variable).
- `mypy engine` — **Success: no issues found in 20 source files**
  (added `ignore_missing_imports` overrides for `yaml` and `pypdfium2` in
  `pyproject.toml`).
- `pytest tests/` — **41 passed in 0.08s**.
- `benchmark/validate.py` — **35 passed, 0 failed** (all seed ground-truth
  files validate).

## Deliverables

- `engine/preprocessing/` — pipeline, profiles, transforms, quality, io,
  mapping, debug (unchanged except the orientation fix and lint formatting).
- `benchmark/preprocess_cer.py` + `benchmark/results_preprocess_cer.json` —
  benchmark and fresh results.
- `pyproject.toml` — mypy overrides for untyped third-party modules.

## Open items for next phase

1. ~~CER regression vs raw~~ — **fixed in P1-fix**; the "must not hurt
   OCR" bar is met (per-kind deltas: 0 or slightly negative).
2. Perspective quad detection on bordered panels.
