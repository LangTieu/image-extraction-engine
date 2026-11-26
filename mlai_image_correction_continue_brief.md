# Brief: CONTINUE image-correction — fix the 4 failing tests + lint, write the report (mlai)

Repo: `/root/image-extraction-engine`, branch `image-correction` (already exists, commit
`86c7918` on it — the liaison moved your round-1 work here from main and restored
main to `81786a7`). Work ON this branch. Do NOT touch main. Do NOT push to main.
Do NOT deploy. Commit on branch `image-correction` only; liaison merges + deploys.
30-minute per-run limit: if time runs out, commit WIP and list remaining items in the report.

## Where round 1 stopped (25/11 ~15:03)
- Round 1 finished with "Not verified" in its own log: no checks ran, no
  `IMAGE_CORRECTION_REPORT.md` was written, work was left uncommitted on main.
- The liaison's independent verification on this branch FAILED:
  - `pytest tests/ -q` exit 1 — 4 NEW tests fail (all yours, in `tests/test_ocr.py`):
    1. `test_deskew_straightens_known_rotation` — AttributeError
    2. `test_sharpen_runs_on_quality_flagged_blur_only` — NameError (truncated in log)
    3. `test_blur_flag_uses_resolution_normalized_variance` — assertion failure
    4. `test_perspective_falls_back_to_border_lines` — NameError
  - `ruff check` exit 1 — 7 errors, incl. E501 line too long at
    `tests/test_ocr.py:445` (102 > 100 chars).
  - GREEN already: `benchmark/validate.py` 35/35, `mypy` 0 errors, validation eval
    F1 0.800, industrial eval routing 1.0 / F1 0.933 / unit 0.875.
- Read the full failure output first: on LV3, `/tmp/lv3v_pytest.log` (pytest) and
  `/tmp/lv3v_ruff.log` (ruff). Read the round-1 log
  `/root/image-extraction-engine/mlai-image-correction.log` for what was changed and why.

## Tasks (in order)
1. **Fix the 4 failing tests.** Each failure is in YOUR new test or YOUR new code —
   find which side is wrong with evidence (run the single test, print the actual
   error) and fix that side. Do NOT weaken an assertion just to make it pass; if
   an expectation was wrong, say so in the report and correct it.
   - `test_deskew_straightens_known_rotation` and `test_perspective_falls_back_to_border_lines`
     look like name/attribute mistakes (missing import or renamed function) — check
     the real function names in `engine/preprocessing/transforms.py` and
     `engine/industrial/screen.py`.
   - `test_blur_flag_uses_resolution_normalized_variance` — check the actual
     variance computation in `engine/preprocessing/quality.py` against the test's
     expectation.
   - The round-1 log also flags: "pipeline.py: its docstring was changed while a
     test was failing. If the test and the documented behaviour disagreed, say which
     one is right before keeping the change." Resolve that disagreement explicitly.
2. **Fix all 7 ruff errors** (no E501 left; keep lines ≤ 100 chars).
3. **Do NOT change `uv.lock`** — round 1 rewrote it by accident; it is already
   restored. Do not touch dependencies.
4. **Re-run the checks yourself, NO pipes** (log to file, read exit codes):
   `.venv/bin/python -m pytest tests/ -q` exit 0;
   `.venv/bin/python -m ruff check .`; `.venv/bin/python -m mypy engine`;
   `python -m benchmark.validate` 35/35. Do NOT run the full benchmark.
5. **Live proof on the two real photos** (`/tmp/tcm-plc.jpg`, `/tmp/coil-table.png`):
   start the API locally (uvicorn on a test port, fresh SQLite, rate limiter off),
   upload each photo, record per photo: which correction steps ran (deskew deg,
   perspective yes/no, sharpen yes/no), OCR word/text-block count before vs after
   (the round-1 baseline is in its log — re-measure it yourself, do not copy
   numbers you did not run). If a step still does not run on a real photo, say so
   plainly — do not claim it works.
6. **Write `IMAGE_CORRECTION_REPORT.md`** in repo root: per real photo, which steps
   ran/skipped before vs after (with the gate/threshold evidence), what changed per
   file, the 4 fixed tests + their pre-fix failure evidence, the live upload proof
   (before/after numbers), and remaining gaps (e.g. 79% glare cannot be fixed by
   sharpening — say so if true). End with the commit hash on `image-correction`.

## Reference
Original brief: `~/workspace/aws-quick/mlai_image_correction_brief.md` (on the VM).
The feature: make the EXISTING preprocessing (deskew / perspective / denoise /
sharpen in `engine/preprocessing/`) actually fire on real photographed screens,
and record what was applied in the job result.
