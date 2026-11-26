# Brief: fix coil_table extraction returning a garbled 24-column table (mlai)

Repo: `/root/image-extraction-engine`, branch `coil-table-fix` fresh from main `379347f`.
Do NOT push to main. Do NOT deploy. Commit on branch `coil-table-fix` only; liaison merges + deploys.
30-minute per-run limit: if time runs out, commit WIP and list remaining items in the report.

## Problem (verified live by the liaison, 25/11 ~13:40)
Henrry uploaded a real photo of a coil list screen ("Day Thong tin.png", saved on this machine as `/tmp/coil-table.png`, 1463x735 PNG). Live job `job_7f3c7aff05d7` returned `document_type: coil_table`, `extraction_status: needs_review`, 1 table, 20 rows, **24 columns** — and the table is garbled (Henrry's screenshot shows it). The raw result proves the bug is in the ENGINE's table extraction, not the UI rendering (the UI faithfully renders the 24-column table the engine produced):
- **Garbage columns on the left.** Columns 0–2 are OCR noise fragments (`V`, `[`, `>'`, `:`, `|`, `oo`, `;`, `0`, `7`, `|`, `/`, `-`, ...). The real table starts around column 3 (`001`, `5`, `S7CBOT?4`, `4.000`, `1243.5`, ...). The left gutter of the screen (row selector / scrollbar / moiré noise) is being parsed as table columns.
- **Duplicated/corrupted header.** Row 0 is a garbage header (`V`, `[`, `>'`, `COL`, `SSIN`, `COLDROLL`, `NG¥`, `'ORK|`, `INIT`, `OO`, `OO`, ...). Row 3 is the REAL header (`SEQ`, `Sts`, `c.COIL`, `HotCoil`, `Weight`, `Stase`, ..., `Tapp.Targ.No`). The header row was picked wrong and the header content also leaks into data rows (rows 1–2 are noise rows).
- **Warnings repeat ~10x.** The `warnings` list contains the same ~24 "unmapped header: ..." entries repeated about 10 times (once per ...?). Same warning text must appear ONCE.
- Context: warnings also say "glare on screen: 79.3% of pixels blown out" and "possible moiré interference (score 1.00)". The coil data rows themselves (001–015, coil IDs, thickness 2.000–4.500, width 954–1544, weight 3000–21080) are mostly CORRECT — so do not rebuild the OCR; fix the table STRUCTURE.
- Note: `text_blocks: 0, fields: 0` on this job is by design (a matched profile keeps fields/tables-only behaviour from the earlier OCR fix) — not part of this bug.

## Tasks
1. **Reproduce locally first.** Run the pipeline on `/tmp/coil-table.png` (benchmark harness or a direct script — the fastest path that exercises the REAL code path) and confirm the 24-column garbled table before the fix. Trace where the garbage columns and the duplicate header come from (region detection? table grid detection? header mapping?).
2. **Fix the table structure, minimally:**
   - Drop noise/gutter columns: columns whose cells are (nearly) all non-alphanumeric noise or empty across data rows must not become table columns. Be careful NOT to drop real narrow columns (e.g. the SEQ column `001`–`015` and the `5`/`2`/`1` status column are real data).
   - Pick ONE header row (the real one) and do not emit header content as data rows.
   - Deduplicate warnings: identical warning text appears once per file result.
3. **Keep the real coil rows intact.** After the fix the table must still contain rows 001–015 with their coil IDs, thickness, width and weight values. Report the before/after column count and row count.
4. **Regression test (REQUIRED, in an EXISTING test file only — do not create a new test file).** Render a synthetic coil-like table image with known rows PLUS a noise gutter column on the left, run the real table pipeline on it, and assert: the noise column is dropped, the header is the real header row (not duplicated as data), and warnings contain no duplicates. The test must FAIL on pre-fix code (prove it) and PASS after.
5. **Live proof on this machine.** Start the API locally (uvicorn on a test port, fresh SQLite file, rate limiter off), upload `/tmp/coil-table.png`, wait for completion, and record: column count, row count, the header row, and 2 sample data rows. Do NOT touch the deployed container.

## Checks (NO pipes — log to file, read exit codes)
- `.venv/bin/python -m pytest tests/ -q` (exit 0; baseline 158 after the UI round).
- `.venv/bin/python -m ruff check .`, `.venv/bin/python -m mypy engine`, `python -m benchmark.validate` 35/35.
- Do NOT run the full benchmark. Do NOT deploy.

## Report
Write `COIL_TABLE_FIX_REPORT.md` in repo root: where the garbage columns/duplicate header/duplicated warnings came from (stage + evidence), what was changed per file, the regression test + pre-fix failure evidence, the live upload proof (before/after columns, rows, header, sample rows), and any remaining gaps (e.g. OCR misreads like `S7CBOT?4` under 79% glare — out of scope unless trivial). End with the commit hash on `coil-table-fix`.
