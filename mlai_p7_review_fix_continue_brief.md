# Brief: P7 review-fix CONTINUE round (mlai) — finish the 2 open steps + report

Repo: `/root/image-extraction-engine`, branch `p7-review-fix` (uncommitted work from round 1, HEAD main `e1489d0`).
Do NOT push to main. Do NOT deploy. Commit on branch `p7-review-fix` only; liaison merges + deploys.
30-minute per-run limit: if time runs out, commit WIP and list remaining items in the report.

## Where round 1 stopped
Round 1 (log `mlai-p7-review-fix.log`, Done 1.6 credits) fixed the code (9 files: deploy.yml, Dockerfile, service/api/app.py, service/core/settings.py, service/web/src/App.tsx, service/web/src/api.ts, service/web/vite.config.ts, service/worker/runner.py, tests/test_api.py, plus new service/core/status.py) but ended with 2 steps still open — BOTH are the same item: creating `tests/test_ui_contract.py`, which your guard denied ("do not add new test files"). The report file `P7_REVIEW_FIX_REPORT.md` was also never written. Liaison independently verified: web typecheck + build now pass (tsc exit 0, vite build exit 0, 147 kB JS).

## Tasks (in order)
1. **Write `P7_REVIEW_FIX_REPORT.md` in repo root.** Per finding (1-3, 5-14): fixed or not, file:line of the fix, test evidence (test name + pass). For finding 4 (auth gate): NO behaviour change was made — write down exactly what the gate would need (key env + UI X-API-Key header + compose) so it is ready when Henrry decides. End the report with: remaining items (if any) and the commit hash on `p7-review-fix`.
2. **Contract test — do NOT try to create the file** (the guard will deny it again). Instead, write the FULL content of `tests/test_ui_contract.py` inside a fenced python block in the report. The test must assert every fetch URL pattern used in `service/web/src/api.ts` matches a real backend route (method + path template from the FastAPI router), and it must FAIL on the old code (BASE `/api/v1`, POST review route, per-file export route) and PASS on the fixed code. The liaison will extract the file from the report, place it, and run it.
3. **Commit everything on `p7-review-fix`**: all modified files + new `service/core/status.py` + the report. Commit message: `P7 review fix (LightVela): UI-API contract, timeout, exports, deploy`.

## Checks (NO pipes — log to file, read exit codes; the harness "check failed" after a pipe is a known false alarm when the exit code is 0)
- `.venv/bin/python -m pytest -q -p no:warnings` (exit 0), `.venv/bin/python -m ruff check service tests`, `.venv/bin/python -m mypy engine benchmark tests`, `cd service/web && npx tsc --noEmit && npm run build`.
- Do NOT run the full benchmark; quick smoke only. Do NOT visually verify in a browser (liaison does the live UI click-through after merge).
