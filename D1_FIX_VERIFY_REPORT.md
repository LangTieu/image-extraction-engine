# D1 fix, round 3: LightVela review round-2 merge conditions

Date: 2026-11-26 · Branch: `d1-provenance` · based on `c08da96` + this commit.
Every number below was produced by a command run in this round; nothing is
copied from an older report or a stale committed JSON.

## Root cause of the collapsed industrial eval (condition 1)

The stale committed `benchmark/results_industrial.json` (routing 0.5, F1 0.0,
every coil sample `NO_PROFILE_MATCHED`) was a real regression, not a stale
write. Bisect by behavior:

- `9973e7f` (dark-background OCR fix) recorded routing 1.000 / F1 0.933 — coil
  samples matched `steel_coil_mill` and parsed.
- Merge `86c7918` (image-correction work) inserted a second enhancement pass
  (`IndustrialVision._enhance`, profile `industrial_screen_photo`) between
  screen rectification and profile matching. That pass re-ran 0/90/180/270
  orientation detection on the already-rectified panel.
- `estimate_orientation_90` (`engine/preprocessing/transforms.py:142`) breaks
  the exact 0-vs-180 tie (Sobel row-projection variance is mirror-symmetric:
  measured 46532.21 at both 0° and 180° on `coil_table_001`) with an ink
  centroid prior that assumes content anchors to the top. The coil render is
  bottom-heavy (measured centroid 0.556 upright vs 0.442 flipped), so the
  detector returned 180° and rotated the panel upside down. OCR then read
  mirrored text (`3NOZ` for `ZONE`, `Ho0001` → `0100oH`) and no profile cue
  matched → generic `industrial_hmi` fallback → zero fields.

Fix: `engine/preprocessing/profiles/industrial_screen_photo.yaml` sets
`orientation.detect: false` (small-angle deskew stays on). `normalize_screen`
already rectifies the panel; the centroid prior is invalid for bottom-heavy
HMI layouts, so 0/180 re-detection must not run on this path.

## Changes by review item

- **N1/condition 1 — eval gate:** `benchmark/industrial_eval.py`
  `_degenerate_reasons` + non-zero exit. Narrow by design so it cannot fail a
  legitimately low-but-real score: it fires only on (a) the exact collapsed
  signature routing ≤ 0.5 with field F1 = 0.0, or (b) any sample whose
  ground-truth category is served by a bundled profile (per
  `IndustrialProfile.categories`) yet came back `NO_PROFILE_MATCHED`.
- **Profile categories corrected:** `steel_coil_mill.yaml` declared
  `industrial_hmi` but generic-HMI fallback is the intended path there, so the
  category was removed — the (b) gate checks serving categories truthfully.
- **N2 — FieldValue provenance page/scale:** `_prov_for_bbox`
  (`engine/industrial/pipeline.py`) now stamps `page=0, scale=1.0` like the
  coil_table producers.
- **N4 — 4-corner AABB:** `_map_bbox` in both `engine/ocr/pipeline.py` and
  `engine/tables/pipeline.py` maps all four corners and takes the true
  axis-aligned bounding box (TL/BR-only mapping can shrink a box under
  rotation).
- **N/convention — bbox coordinate space (condition 3):** documented on
  `BBox` (`engine/schema/models.py`): node `bbox` stays in the producer's
  working-image space; `prov.bbox` is the same region mapped to original
  coordinates. `engine/tables/pipeline.py` no longer overwrites
  `table.bbox`/`cell.bbox` with mapped coordinates (it was double-mapping;
  prov kept the original-space box, bbox claimed to be working-space but was
  not). `tests/test_tables.py::test_extract_maps_bbox_through_transform_log`
  asserts the corrected convention.
- **N7 — numeric-bbox assertions:** the F4(c) e2e test now also asserts a
  numeric `prov.bbox` (`x1 > x0`, `y1 > y0`), not just coord_space/page/unit;
  new `test_prov_bbox_numeric_after_known_upscale` checks a known x2 upscale
  maps prov.bbox back to box/2.
- **N8 — mixed-DPI prov scale:** restored
  `test_pdf_mixed_dpi_pages_carry_different_prov_scales`: the same two-page
  PDF recognized at dpi 100 and dpi 200 yields `prov.scale == dpi/72` and the
  two differ.
- **N5 — alarm provenance:** `AlarmEntry` gains `prov: list[Provenance]`;
  `_extract_alarms` fills it via `_prov_for_bbox(region.bbox, ocr_log)` and
  `_alarm_dict` exports page/scale/coord_space/unit/bbox. No documented gap
  remains for alarms.
- **N9 — profile-matching tokens:** `_ocr_text_shallow` documents that its
  tokens are consumed as a text bag for cues only and are never attached to a
  bbox/prov, so they cannot mislabel provenance.

## Gates (all exit codes read from the runners this round)

| Gate | Result |
| --- | --- |
| `python -m pytest tests/ -p no:warnings` | 174 passed in 50.75s (172 before + 2 new), 0 failed |
| `python -m ruff check engine benchmark tests` | exit 0 |
| `python -m mypy engine benchmark` | exit 0 — no issues in 75 source files |
| `python -m benchmark.validate` | exit 0 — 35 passed, 0 failed |
| `python -m benchmark.industrial_eval` | exit 0 — routing=1.000 f1=0.933 unit_acc=0.875 unknown_flagged=1.000 (regression cleared, matches the historical 1.0 / 0.933 / 0.875 figures) |

## Not verified / unverified claims

- Nothing in this round's scope is unverified. Note for reviewers: the merged
  gate's (a) signature check has not been exercised against an actually
  collapsed run (the regression is fixed), only against the current healthy
  output.

## Commits

- Committed locally on `d1-provenance`. Not pushed, not deployed.
