# P3-TATR brief — evaluate the Table Transformer backend on LV3 (mlai, LV3)

## Context
P3 (Table Extraction) is done except the Table Transformer (TATR) backend,
which was blocked on IB4 by disk space. The project has moved to LV3
(`/root/image-extraction-engine`, 22 GiB free) — the disk blocker is gone.
This run evaluates TATR only. Do NOT start P4.

## Task
1. Download the Table Transformer detection + structure weights
   (microsoft/table-transformer-detection and -structure, or the exact
   models `engine/tables/tatr.py` expects) into the local HF cache.
   LV3 has 22 GiB free — downloading ~1 GiB is fine.
2. Run the TATR backend through the existing evaluation
   (`benchmark/tables_eval.py`): detection recall, structure accuracy
   (TEDS/cell-adjacency), cell-content accuracy, latency per table —
   reported separately for ruled / borderless / dense small-font / coil
   tables, and compared against the ruled, borderless and hybrid backends.
3. Verify the hybrid mode with TATR included is at least as good as the
   best single backend on dense tables (P3 acceptance criterion).
4. Update `docs/reports/p3_tables.md` with the TATR results and the
   recommended default backend per table type. Update `P3_REPORT.md`:
   TATR section with actual numbers, remove the disk-blocked note.
5. Delete `BLOCKED.md` (the disk blocker is resolved by the LV3 move).
6. Run `.venv/bin/python -m pytest tests/ -q` (all pass),
   `.venv/bin/python benchmark/validate.py` (35 passed),
   `ruff check engine benchmark tests` and `mypy engine` (both clean).
   Then stop.

## Standing rules (do not break)
- Add-only to shared files; never rewrite a shared file from scratch.
- NEVER `rm -rf` anything. Never delete files except `BLOCKED.md` (step 5)
  and ones this run creates.
- NEVER deploy, commit or push — the liaison does that.
- NEVER install packages (apt/pip/uv) — the liaison installs what you need.
  If a package is missing, STOP and write it into `BLOCKED.md`.
- If you get stuck: STOP. Write the blocker and exactly what you need
  into `BLOCKED.md` in the project dir, then stop the run. Do NOT guess,
  do NOT work around it silently, do NOT skip ahead to P4. The liaison
  checks the log every 5 minutes and will supply what you need.
