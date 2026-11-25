# Image Correction Report (liaison-written from evidence — mlai rounds 1+2 left no report)

Branch: `image-correction` → main. Commits: `86c7918` (round 1) + `6f07531`
(continue round: cv2 import, rotation sign, line lengths). Report written by the
liaison from the diff, the test runs and a live proof the liaison ran itself
(mlai's own log says round 1 was "Not verified"; the continue round stopped
mid-check, so the numbers below are the liaison's independent verification).

## What Henrry asked (25/11 13:56)
Beyond text extraction, add correcting skewed/distorted + blurry photos. The
engine already had `engine/preprocessing/` (deskew, perspective, denoise,
contrast, sharpen) but its gates never fired on his two real photos.

## What changed (diff 81786a7..image-correction, 7 files, +268/−15)
- `engine/industrial/screen.py` — `detect_screen_quad` gains two fallbacks:
  border-line quad, then a gradient (brightness-contrast) quad; a quad is only
  accepted when the screen interior differs from its surroundings
  (`_screen_has_contrast`).
- `engine/preprocessing/quality.py` — blur flag uses resolution-normalised
  Laplacian variance (was absolute, so big photos never flagged).
- `engine/preprocessing/transforms.py` — deskew rotation sign fixed.
- `engine/preprocessing/pipeline.py` — TOO_BRIGHT removed from the denoise
  gate (denoise cannot fix saturation, only risks smearing a clean bright
  screenshot); docstring corrected to match the tested behaviour.
- `engine/preprocessing/profiles/industrial_screen_photo.yaml` — profile tuned.
- `engine/industrial/pipeline.py` — shares the one whole-frame OCR pass.
- `tests/test_ocr.py` — 4 new tests (see below).

## Verification (liaison, branch image-correction @ 6f07531)
- pytest: exit 0 (full suite, incl. the 4 new tests — round 1 had left all 4
  failing: AttributeError / NameError / assertion; the continue round fixed them).
- ruff: exit 0 (round 1 had 7 errors, incl. E501). mypy: 0 errors.
- `benchmark/validate.py`: 35/35. Validation eval F1 0.800 (unchanged).
  Industrial eval: routing 1.0 / field F1 0.933 / unit 0.875 (unchanged).
- `uv.lock` was rewritten twice by the rounds (+1257 lines, unasked) — restored
  by the liaison both times; it is NOT in the merged commits.

## Live proof on the two real photos (liaison, local uvicorn :3214, branch code)
| Photo | Before (main 81786a7 / 0a1ded0) | After (image-correction) |
|---|---|---|
| TCM PLC (`/tmp/tcm-plc.jpg`, 1672×941) | 13 text_blocks (local) / 15 (live), 0 fields, 43–50 s, warnings incl. "screen boundary not detected; using full frame" | **13 text_blocks, 0 fields, 46 s, warning "screen boundary not detected" GONE** |
| Coil list (`/tmp/coil-table.png`, 1463×735) | 1 table 17×21, header SEQ…TAPP.TARG.NO, 36 unique warnings, ~105 s | **1 table 17×21, same header, 36 unique warnings, 170 s** (slower — machine load was 25 at the time) |

- **Perspective fix PROVEN on the real TCM photo:** `screen.py:207` calls
  `detect_screen_quad` and line 217 appends "screen boundary not detected"
  only when it returns None. The after-run has no such warning, so the
  border-line/gradient fallback found a quad where the old code fell back to
  full-frame. OCR block count did not move (13 = baseline) and fields are
  still 0 — the correction engages, but it does not yet recover more text
  from this glare-heavy photo.
- **Deskew / sharpen:** synthetic tests pass (5° skew straightened, blur flag
  fires only on quality-flagged blur, clean scan stays a perspective no-op).
  No measurable change on the two real photos (coil table identical).
- **Corrections are recorded in-process but NOT surfaced in the API job result:**
  `IndustrialVision` records `extensions["industrial"]["corrections"]`
  (profile, deskew_deg, perspective_corrected — see pipeline.py `_corrections_dict`),
  but the API result's `processing` dict still holds only `pipeline_path` /
  `module_versions` / `timings_ms`. Surfacing the corrections in the job
  result JSON is backlog, not in this merge.

## New tests (all in tests/test_ocr.py, fail pre-fix, pass post-fix)
- `test_deskew_straightens_known_rotation` (5° synthetic skew)
- `test_sharpen_runs_on_quality_flagged_blur_only`
- `test_blur_flag_uses_resolution_normalized_variance`
- `test_perspective_falls_back_to_border_lines` (TCM photo: quad found)

## Remaining gaps (honest)
- Fields still 0 on the TCM photo (glare-corroded label crops; separate
  limitation, needs the glare-robust field reader).
- Correction steps not recorded in the job result (see above).
- Coil job slower this run (170 s vs 105 s) — not attributed; watch on live.
- `benchmark/artifacts/p8review_81786a72/` untracked dir left on LV3, not committed.
