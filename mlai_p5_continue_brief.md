# P5 continue brief — finish checks + raise recall (mlai, LV3)

## Context
Working dir on THIS machine: `/root/image-extraction-engine`.
The P5 run stopped at the step limit (184 model calls) after writing
`P5_REPORT.md` and `docs/reports/p5_validation.md`. The code is in place
(`engine/validation/` + `benchmark/validation_eval.py` +
`tests/test_validation.py`). Finish ONLY the items below — do not start P6,
do not redesign anything.

## Remaining items (in order)
1. Run the final checks the first run could not: `.venv/bin/ruff check
   engine benchmark tests` and `.venv/bin/mypy engine` — fix what they
   report. Then run the FULL test suite `.venv/bin/python -m pytest
   tests/ -q` (all test files, not just test_validation.py) and
   `.venv/bin/python benchmark/validate.py`. All must pass; record the
   exact counts in the report.
2. Raise error-detection recall. The seeded eval reports precision 1.00
   / recall 0.20 / F1 0.33 — the P5 brief's acceptance target is
   error-catch recall >= 95% with the review rate reported. Widen
   `rules/default.yaml` (and `rules/steel_coil_mill.yaml` where it
   applies): add range rules for the numeric columns present in the seed
   layouts, cross-field consistency (e.g. weight vs thickness/width/
   length/density), unit-column checks and row-count checks, so more of
   the injected wrong values are caught by a declared rule. Re-run
   `.venv/bin/python -m benchmark.validation_eval benchmark/seed` and
   report the new precision/recall/F1 AND the review rate at the
   auto-accept threshold. If recall still cannot reach 95%, report the
   final number honestly with the concrete reason — do NOT redefine the
   target, do NOT lower the injected error rate, do NOT drop hard cases
   from the eval.
3. Update `P5_REPORT.md` with the final numbers (pytest total, validate,
   ruff, mypy, eval precision/recall/F1, review rate, ECE) and the
   final list of what changed in this continue run, then stop.

## Standing rules (do not break)
- Add-only to shared files; never rewrite a shared file from scratch.
- NEVER `rm -rf` anything. NEVER delete files.
- NEVER deploy, commit or push — the liaison does that.
- NEVER install packages (apt/pip/uv) — the liaison installs what you need.
  If a package is missing, STOP and write it into `BLOCKED.md`.
- If you get stuck: STOP. Write the blocker and exactly what you need
  into `BLOCKED.md` in the project dir, then stop the run. Do NOT guess,
  do NOT work around it silently, do NOT skip ahead to P6.
