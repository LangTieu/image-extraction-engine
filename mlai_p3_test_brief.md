# P3-test brief — add durable P3 tests (mlai, IB4)

## Task (one fix only, do not start P4)
Add the missing P3 pytest coverage. `P3_REPORT.md` notes
`tests/test_tables.py` could not be created (the harness denied the
new-test-file write twice). The user (the liaison, on Henrry's behalf)
explicitly asks for it now — this IS the user asking.

## Items
1. Add `tests/test_tables.py` (the suite is already written per
   `P3_REPORT.md` — paste/add it): ruled backend grid detection,
   borderless token clustering, hybrid reconciliation (IoU matching,
   higher-scored grid wins), cell assignment (straddling tokens,
   multi-line cells, `normalize_column_key`), header detection +
   `column_N` fallbacks, empty cells explicitly null with a reason,
   multi-page merge (`merge_pages` continuation), `bbox_original`
   mapping through a TransformLog, TATR backend raising
   `TableBackendUnavailable` without cached weights (never downloads),
   and the coil-table regression suite proving no silent column shifts.
   Use small synthetic fixtures (rendered tables via PIL, tiny PDFs) —
   do NOT download models in tests.
2. Run `.venv/bin/python -m pytest tests/ -q` — all tests (old + new)
   must pass. Run `ruff check engine benchmark tests` and `mypy engine` —
   both clean.
3. Run `.venv/bin/python benchmark/validate.py` — must still pass.
4. Update `P3_REPORT.md`: new test count, what the tests cover. Then stop.

## Standing rules (do not break)
- Add-only to shared files; never rewrite a shared file from scratch.
- NEVER `rm -rf` anything. Never delete files except ones this fix creates.
- NEVER deploy, commit or push — the liaison does that.
- If you get stuck: STOP. Write the blocker and exactly what you need
  into `BLOCKED.md` in the project dir, then stop the run. Do NOT guess,
  do NOT work around it silently, do NOT skip ahead to P4. The liaison
  checks the log every 5 minutes and will supply what you need.
- If the harness denies creating the test file again, STOP and write that
  exact denial into `BLOCKED.md` instead of working around it.
