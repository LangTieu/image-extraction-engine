# P4 fix continue brief — finish the fix round (mlai, LV3)

## Context
Working dir on THIS machine: `/root/image-extraction-engine`.
This is a CONTINUE run: the P4 fix run stopped after the eval improved
but before updating the docs. Read `mlai_p4_fix_brief.md` first for the
full fix task, then do ONLY the remaining items below. Do NOT redo
finished work. Do NOT start P5.

## What is already done
- The dark-background fix works: eval14 shows routing 1.000, F1 0.933,
  unit_acc 0.875, unknown_flagged 1.000 (was routing 0.500, F1 0.000).
- pytest 80 passed (see pytest_final.log).

## Remaining items (do them in this order)
1. Re-read `benchmark/results_industrial.json` and `/tmp/eval14.log` to
   confirm the eval numbers yourself. Report the REAL numbers — never
   invent or round them up.
2. Update `docs/reports/p4_industrial.md` with the new eval numbers
   (routing, F1, unit_acc, unknown_flagged, coil_table routing).
3. Append a short "Fix round" section to `P4_REPORT.md` (what changed,
   new numbers, checks run).
4. Rerun all four checks and record the results in `P4_REPORT.md`:
   `.venv/bin/python -m pytest tests/ -q`,
   `.venv/bin/python benchmark/validate.py`,
   `ruff check engine benchmark tests`, `mypy engine` — all must pass.
   Then stop. Do NOT create files under `tests/` in this run.

## Standing rules (do not break)
- Add-only to shared files; never rewrite a shared file from scratch.
- NEVER `rm -rf` anything. NEVER delete files.
- NEVER deploy, commit or push — the liaison does that.
- NEVER install packages (apt/pip/uv) — the liaison installs what you need.
  If a package is missing, STOP and write it into `BLOCKED.md`.
- If you get stuck: STOP. Write the blocker and exactly what you need
  into `BLOCKED.md` in the project dir, then stop the run. Do NOT guess,
  do NOT work around it silently, do NOT skip ahead to P5.
