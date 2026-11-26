# Brief: CONTINUE coil-table fix — finish the unfinished items (mlai)

Repo: `/root/image-extraction-engine`, branch `coil-table-fix` (already exists, commit
`f90ceff` on it). Do NOT push to main. Do NOT deploy. Commit on branch `coil-table-fix`
only; liaison merges + deploys.
30-minute per-run limit: if time runs out, commit WIP and list remaining items in the report.

## Where the previous round stopped (30-min limit, 25/11 ~14:12)
Read the previous round's log `/root/image-extraction-engine/mlai-coil-table-fix.log`
and report `COIL_TABLE_FIX_REPORT.md` (WIP) first, then finish exactly these items:
1. **Engine fix is DONE (commit f90ceff).** Verify it is still intact; do not redo it.
2. **Uncommitted test changes:** `tests/test_ocr.py` was modified but not committed.
   Review the diff, keep it, commit it.
3. **Failing regression test:** the new test `test_coil_table_drops_noise_columns_and_toolbar_rows`
   FAILS (pytest `assert False` in the log). Debug it against the real pipeline on
   `/tmp/coil-table.png` (1463x735, the real coil photo; live job `job_7f3c7aff05d7`
   returned a 24-column garbled table, header duplicated, warnings repeated ~10x).
   Fix the test or the code — whichever is actually wrong — with evidence. The test
   must PASS after this round. If the test's expectation was wrong, say so plainly
   in the report and correct the expectation.
4. **Live proof (still missing):** start the API locally (uvicorn on a test port,
   fresh SQLite file, rate limiter off), upload `/tmp/coil-table.png`, wait for
   completion, and record: column count, row count, the header row, 2 sample data
   rows (001–015 coil rows must be intact). Compare against the pre-fix live result
   (24 columns, garbage header row 0, real header row 3).
5. **Checks (NO pipes — log to file, read exit codes):** `.venv/bin/python -m pytest
   tests/ -q` exit 0; `.venv/bin/python -m ruff check .`; `.venv/bin/python -m mypy
   engine`; `python -m benchmark.validate` 35/35. Do NOT run the full benchmark.
6. **Finish the report:** update `COIL_TABLE_FIX_REPORT.md` (it is WIP): the two
   root causes found (header alias mismatch 'HotCoil' vs 'hot_coil_no'; header_index
   lost when the toolbar header yields no field type), what changed per file, the
   regression test + pre-fix failure evidence, the live upload proof (before/after
   columns, rows, header, sample rows), and remaining gaps. End with the commit
   hash on `coil-table-fix`.

## Reference
Original brief: `~/workspace/aws-quick/mlai_coil_table_fix_brief.md` (on the VM, not
on LV3 — the summary: drop noise/gutter columns left of the real table, pick ONE
header row, dedupe identical warnings; keep coil rows 001–015 intact).
