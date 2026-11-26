# Brief: make image correction actually run on real screen photos (deskew / perspective / deblur) (mlai)

Repo: `/root/image-extraction-engine`, branch `image-correction` fresh from main (whatever main is when this launches — the coil-table-fix merge if it landed first).
Do NOT push to main. Do NOT deploy. Commit on branch `image-correction` only; liaison merges + deploys.
30-minute per-run limit: if time runs out, commit WIP and list remaining items in the report.

## Background (verified by the liaison, 25/11)
The engine ALREADY has `engine/preprocessing/` (transforms.py + pipeline.py + profiles):
orientation + deskew (Hough lines), perspective correction (quad detection), denoise,
contrast, sharpen (`SharpenConfig.require_quality_flag` — sharpen only runs when the
quality gate flags blur), glare, crop, upscale. BUT on Henrry's two real photos it
did NOT help in practice:
- TCM photo `/tmp/tcm-plc.jpg` (1672x941): warning "screen boundary not detected;
  using full frame" — perspective correction SKIPPED (no quad found); text came out
  rough, fields 0.
- Coil photo `/tmp/coil-table.png` (1463x735): warnings "glare on screen: 79.3% of
  pixels blown out", "possible moiré interference (score 1.00)"; the extracted table
  came out garbled (24 columns incl. 3 noise columns, duplicated header).
So this round is NOT about writing a new preprocessor from scratch. It is about
making the existing one actually fire on real photographed screens, and making its
effect visible.

## Tasks
1. **Diagnose with evidence first.** For BOTH real photos (`/tmp/tcm-plc.jpg`,
   `/tmp/coil-table.png`), run the preprocessing pipeline directly and record, per
   step: ran / skipped / why (which gate, which threshold, what the detector saw).
   Report the exact gate/threshold that blocks perspective correction on the TCM
   photo (quad not found — why? glare? low edge contrast? tolerance too tight?)
   and whether sharpen/denoise ran on the coil photo (blur flag fired or not?).
2. **Fix the gates/detection, minimally, with numbers:**
   - Perspective: make quad detection work on glare-heavy screen photos (e.g. relax
     the frame-quad tolerance / edge thresholds, or add a fallback that uses the
     dominant screen border lines). It must NOT warp clean document scans that need
     no correction (guard with the existing quality gate; a no-op on clean input is
     a PASS, not a skip to remove).
   - Deblur/sharpen: sharpen/denoise must run when the photo is actually blurry
     or low-contrast, not only when the existing blur flag fires — fix the flag or
     add a second trigger (e.g. Laplacian-variance / edge-strength threshold).
     Cap the strength so text does not get halo artefacts (verify on the two photos).
   - Deskew: confirm the Hough deskew angle is applied for both photos; if the
     angle estimate is wrong on either, fix it.
3. **Make the correction VISIBLE.** The job result (and the UI, if the field
   already exists — do not invent new API routes) must record what was applied
   (e.g. `corrections: {deskew_deg, perspective: true/false, sharpen: true/false}`)
   so the user can see the photo was corrected. If the pipeline already logs
   this in `processing`, surface it; do not add a new endpoint.
4. **Prove the improvement on the two real photos.** Before/after, per photo:
   OCR word count (plain tesseract baseline is 542 words for TCM), extracted
   text_blocks / fields / tables, and the correction steps that ran. The fix is
   only real if the numbers move (or, at minimum, do not regress while the
   corrections now provably run).
5. **Regression tests (REQUIRED, in EXISTING test files only).** One synthetic
   skewed image (known rotation, e.g. 5 degrees) — assert the deskew step
   straightens it within tolerance. One synthetic blurred image — assert sharpen/
   denoise runs and the OCR word count improves vs uncorrected. One clean scan —
   assert perspective is a no-op. Tests must FAIL on pre-fix code, PASS after.
   If a test cannot fail pre-fix (e.g. deskew already works on synthetic input),
   say so plainly in the report and use the REAL photos as the proof instead.

## Checks (NO pipes — log to file, read exit codes)
- `.venv/bin/python -m pytest tests/ -q` (exit 0; baseline = whatever the suite is
  when this runs — the UI round left it at 158, the coil round may add more).
- `.venv/bin/python -m ruff check .`, `.venv/bin/python -m mypy engine`,
  `python -m benchmark.validate` 35/35.
- Do NOT run the full benchmark. Do NOT deploy. Do NOT touch the deployed container.

## Report
Write `IMAGE_CORRECTION_REPORT.md` in repo root: per real photo, which steps
ran/skipped before vs after (with the gate/threshold evidence), what changed per
file, regression tests + pre-fix failure evidence, before/after OCR numbers for
both photos, and remaining gaps (e.g. 79% glare cannot be fixed by sharpening —
say so if true). End with the commit hash on `image-correction`.
