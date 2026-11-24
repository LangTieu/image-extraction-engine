# P4 fix brief — dark-background OCR (mlai, LV3)

## Context
Working dir on THIS machine: `/root/image-extraction-engine`.
P4 is built, verified and committed (commit 4c91efa on main). All checks
are green (pytest 80, mypy 0 errors, ruff green, validate 35/35). But the
eval shows a real gap in the module's core case — this run fixes that gap
only. Do NOT start P5.

## The gap (from P4_REPORT.md, verified by the liaison)
- `benchmark/industrial_eval.py` renders GT tables as ruled grids on a
  dark HMI background with small text.
- Routing accuracy 0.500: `industrial_hmi` 5/5, `coil_table` 0/5 — OCR
  cannot read the small dark-background table text, so the coil
  vocabulary rule never fires and the pipeline takes the documented
  `NO_PROFILE_MATCHED` fallback.
- Field F1 0.000, unit accuracy 0.000 (direct consequence).
- `unknown_flagged` 1.000 — every unmatched field is flagged, none dropped
  (keep this behavior).

## Task
Fix the dark-background OCR gap in `engine/industrial/` (screen
normalization and/or compact OCR — pick the right place):
- Detect a dark background (e.g. mean luminance) and invert to
  dark-on-light before OCR, so bright-on-dark HMI text becomes readable.
- Increase the upscale factor for small text crops where needed.
- Keep the fix inside the Industrial Vision module; do not change General
  Vision behavior for non-industrial images.

## Checks (all must pass, then stop)
1. `.venv/bin/python -m benchmark.industrial_eval` — report the new
   numbers honestly: `coil_table` routing and field F1 MUST rise above 0
   (target: coil_table at least 3/5); `industrial_hmi` must stay 5/5.
   If the numbers do not improve after a genuine attempt, say so in the
   report with the reason — do not inflate numbers or weaken the eval.
2. `.venv/bin/python -m pytest tests/ -q` (80 passed),
   `.venv/bin/python benchmark/validate.py` (35 passed),
   `ruff check engine benchmark tests`, `mypy engine` — all green.
3. Update `docs/reports/p4_industrial.md` with the new eval numbers and
   append a short "Fix round" section to `P4_REPORT.md` (what changed,
   new numbers), then stop. Do NOT create files under `tests/` in this run.

## Standing rules (do not break)
- Add-only to shared files; never rewrite a shared file from scratch.
- NEVER `rm -rf` anything. NEVER delete files.
- NEVER deploy, commit or push — the liaison does that.
- NEVER install packages (apt/pip/uv) — the liaison installs what you need.
  If a package is missing, STOP and write it into `BLOCKED.md`.
- If you get stuck: STOP. Write the blocker and exactly what you need
  into `BLOCKED.md` in the project dir, then stop the run. Do NOT guess,
  do NOT work around it silently, do NOT skip ahead to P5.
