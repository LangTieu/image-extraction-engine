# Brief: show extracted text_blocks in the UI + fix timestamp/badge (mlai)

Repo: `/root/image-extraction-engine`, branch `ui-text-blocks` fresh from main `0a1ded0`.
Do NOT push to main. Do NOT deploy. Commit on branch `ui-text-blocks` only; liaison merges + deploys.
30-minute per-run limit: if time runs out, commit WIP and list remaining items in the report.

## Problem (verified live by a browser click-through, 25/11 ~13:20)
The web app at https://ocr.aistockvn.com/ works end to end (upload → processing → review → JSON export), but the extracted text is INVISIBLE in the UI:
- A real HMI photo job (`job_8c172da4bc17`, live) completed with **15 text_blocks, 0 fields, 0 tables**. The downloaded JSON export contains all 15 blocks (verified by the liaison from the downloaded file). But the Review view shows the source image with NO bounding-box overlays and NO selectable text — clicking the image selects nothing, "Selected item" keeps prompting to select a field/table cell/box. The Fields panel says "This file has no standalone fields" and Results says "No fields were extracted". So a user who never downloads the JSON sees no extraction output at all.
- Root cause (expected): the v0 UI was built before the OCR fix added `text_blocks` to results, so no view renders them.

## Tasks
1. **Review view: render `text_blocks` as bounding-box overlays on the source image.** Each block's `bbox` (`x0,y0,x1,y1` in image pixels) maps onto the displayed image (scale to the displayed size; the image has zoom Fit width / 100%). Blocks must be clickable/selectable, showing the block text + confidence in the "Selected item" panel. Also add a plain text list of the blocks (reading order) on the Review and/or Results page, so the extracted text is readable as text without downloading JSON. Keep existing field/table behaviour unchanged (fields/tables still render as before; when a job has both, show both).
2. **Relative timestamps off by ~7 hours.** Jobs/Results lists showed "7 h ago" for a job created ~2 minutes earlier, while the job detail page shows the correct absolute times. The backend stores UTC; the UI's relative-time code treats it as local (or vice versa). Fix so relative times are correct in the user's timezone (Asia/Saigon is the owner's timezone, but the fix must be correct for any viewer timezone — parse the timestamp as UTC, then compute relative time against the viewer's clock).
3. **Sidebar "Jobs" badge stuck at "1 in progress".** After all jobs completed, the badge still read "1 in progress". Fix the badge count to reflect live job statuses (recompute from the jobs list, not a stale counter).

## Regression tests (REQUIRED, in EXISTING test files only — do not create new test files)
- Extend `_collect_ui_calls` style contract tests in `tests/test_api.py` (or the existing UI contract test) so the Review/Results views are asserted to reference `text_blocks` (e.g. the built JS or the source must read `text_blocks` from the result payload). The test must FAIL on pre-fix code and PASS after.
- If the timestamp fix is in a shared util, add a unit test for it in the existing test file covering UTC parsing (a job created 2 minutes ago must render as minutes, not hours).

## Checks (NO pipes — log to file, read exit codes)
- `.venv/bin/python -m pytest tests/ -q` (exit 0; baseline 156).
- Web build: `npm run build` in service/web (exit 0) + grep the dist output for `text_blocks` usage (must be present) and for any `/api/v1` (must be absent).
- `.venv/bin/python -m ruff check .`, `.venv/bin/python -m mypy engine service` (service mypy if configured; otherwise engine only — note it in the report).
- Do NOT deploy. Do NOT run the full benchmark.

## Live proof on this machine
Start the API locally (uvicorn on a test port, fresh SQLite, rate limiter off), upload `/tmp/tcm-plc.jpg`, wait for completion, and confirm via the API result that the job carries 15 text_blocks (or the current count) — then confirm the built web bundle serves the new Review code (grep dist for the overlay component name). Do NOT touch the deployed container.

## Report
Write `UI_TEXT_BLOCKS_REPORT.md` in repo root: what was changed per file, the regression tests + pre-fix failure evidence, the live proof, and any remaining gaps. End with the commit hash on `ui-text-blocks`.
