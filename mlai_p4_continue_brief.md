# P4 continue brief — finish Industrial Vision (mlai, LV3)

## Context
Working dir on THIS machine: `/root/image-extraction-engine`.
This is a CONTINUE run: the first P4 run used all 120 steps and stopped.
Read `mlai_p4_brief.md` first for the full P4 task, then do ONLY the
remaining items below. Do NOT redo finished work. Do NOT start P5.

## What is already done (verified by the liaison)
- `pytest tests/` 80 passed, `benchmark/validate.py` 35 passed / 0 failed,
  ruff green, `benchmark/industrial_eval.py` runs.
- `engine/industrial/` exists (screen normalization, region detection,
  compact OCR, coil table mapping, value/unit/alarm extraction, profile
  loader, fallback parser), sample profiles exist, router categories
  registered.

## Remaining items (do them in this order)
1. **Seed PNGs — restore, do not regenerate.** The liaison verified:
   the PNGs under `benchmark/seed/` in git (HEAD) are ALREADY 1x1
   placeholder images (69 bytes) — they were never real scenes. Your
   rewrite made them 68 bytes; no real data was lost. Run
   `git checkout -- benchmark/seed/` to remove the diff noise, and do
   NOT regenerate the seed PNGs again.
2. **Fix the eval, not the images.** `industrial_eval` currently reads
   the stored placeholder PNGs, so it scores F1 0.000 on blank images.
   Find how the P2/P3 evals obtained real images ("rendered GT scenes")
   and make `industrial_eval.py` render scenes from the seed JSON at
   runtime the same way. Never report eval numbers measured on blank
   1x1 images as real results.
3. **mypy: 16 errors in `engine/industrial/`** (literal status typing,
   `ProcessingMeta`, an OCR method name, `BBox` kwargs, ndarray types).
   You already identified the fixes in the previous run — apply them.
4. **Generalize the two `ndim == 3` branches** in `alarms.py` and
   `compact_ocr.py` to arbitrary channel counts.
5. **Rerun all four checks:** `.venv/bin/python -m pytest tests/ -q`,
   `.venv/bin/python benchmark/validate.py`,
   `ruff check engine benchmark tests`, `mypy engine` — all must pass.
   Then run `benchmark/industrial_eval.py` and record the REAL Coil ID
   exact-match accuracy, field accuracy, unit-association accuracy and
   latency in `docs/reports/p4_industrial.md`.
6. **Write `P4_REPORT.md`** (what was built, check results, eval
   numbers) and stop. Do NOT create files under `tests/` in this run —
   a separate test brief will add the P4 tests.

## Standing rules (do not break)
- Add-only to shared files; never rewrite a shared file from scratch.
- NEVER `rm -rf` anything. NEVER delete files.
- NEVER deploy, commit or push — the liaison does that.
- NEVER install packages (apt/pip/uv) — the liaison installs what you need.
  If a package is missing, STOP and write it into `BLOCKED.md`.
- If you get stuck: STOP. Write the blocker and exactly what you need
  into `BLOCKED.md` in the project dir, then stop the run. Do NOT guess,
  do NOT work around it silently, do NOT skip ahead to P5.
