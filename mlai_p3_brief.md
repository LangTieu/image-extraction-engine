# P3 brief — Table Extraction (mlai, IB4)

## Task
Implement P3 (Table Extraction) per the P3 prompt in `prompts_aws_quick.md`
(lines 178–~230). This is ONE phase only. Do not start P4.

## Scope (from the P3 prompt)
- `engine/tables/` package: `detect.py` (`TableDetector.detect(image) ->
  list[TableRegion]` with bbox + confidence), structure recognition with
  TWO backends — Table Transformer (detection + structure models) for
  complex/borderless tables, and OpenCV + OCR (P2 backends) for ruled
  tables (morphological lines, intersections, cell grid; borderless:
  cluster OCR token x into columns, y into rows). Backend selectable per
  profile + hybrid mode reconciling both.
- Cell assignment: OCR tokens → cells by bbox overlap (straddling tokens,
  multi-line cells); re-OCR low-confidence cell crops via the P2
  multi-scale hook.
- Headers and spans: header rows (position/styling/text cues), multi-level
  headers, row/col spans. Columns as ordered header names with stable
  normalized keys (e.g. HOT_COIL_NO).
- Column alignment integrity: NEVER shift values between columns. Empty
  cells stay explicitly empty (null with a reason), never filled with
  neighbours.
- Multi-page tables: merge continuations across PDF pages when headers match.
- Output: populate the unified schema `tables[]` (table_name, columns,
  rows as dicts keyed by column, cells[] with row/col/spans/text/bbox in
  ORIGINAL coordinates/confidence, table-level confidence).
- Debug visualization: overlay detected grid + cell IDs on the image.
- Evaluation: Table Structure Accuracy (TEDS or cell-adjacency from P0)
  + cell-content accuracy, reported separately for ruled / borderless /
  dense small-font / coil tables, with latency per table. Compare backends
  + hybrid.
- Deliverable: `docs/reports/p3_tables.md` (structure-accuracy results,
  recommended default per table type) + `tests/test_tables.py` (incl. a
  regression suite of coil tables proving no silent column shifts).

## Done means (all must hold)
- Detection recall >= 95% on benchmark table images (record the actual
  figure). Hybrid mode at least as good as the best single backend on
  dense tables. Every cell value traces to its cell bbox in original
  coordinates. Empty/uncertain cells explicitly marked with warnings.
  Backend switchable by configuration.
- `.venv/bin/python -m pytest tests/ -q` — ALL tests pass (old + new).
- `.venv/bin/python benchmark/validate.py` — 35 passed, 0 failed.
- `ruff check engine benchmark tests` clean; `mypy engine` clean.
- Write `P3_REPORT.md` (status COMPLETE, what was delivered, verified
  results with actual numbers, deviations). Then stop.

## Disk guard (IMPORTANT — /data is 92% full, ~1.5 GiB free)
- Before downloading ANY model (Table Transformer weights, etc.), run
  `df -h /data`. If free space < 2 GiB, STOP and write that into
  `BLOCKED.md` — do NOT download. The liaison will free space or grow
  the disk. Prefer the smallest working model variant; do not download
  models you do not use in this phase.

## Standing rules (do not break)
- Add-only to shared files; never rewrite a shared file from scratch.
- NEVER `rm -rf` anything. Never delete files except ones this phase creates.
- NEVER deploy, commit or push — the liaison does that.
- NEVER install packages (apt/pip/uv) — the liaison installs what you need.
  If a package is missing, STOP and write it into `BLOCKED.md`.
- If you get stuck: STOP. Write the blocker and exactly what you need
  into `BLOCKED.md` in the project dir, then stop the run. Do NOT guess,
  do NOT work around it silently, do NOT skip ahead to P4. The liaison
  checks the log every 5 minutes and will supply what you need.
