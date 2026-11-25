# Brief: P7 review-fix round (mlai) — fix LightVela AI's P7 review findings

Repo: `/root/image-extraction-engine` (branch `p7-review-fix`, fresh from main HEAD `e1489d0`).
Do NOT push to main. Do NOT deploy. Commit on branch `p7-review-fix` only; liaison merges + deploys.
30-minute per-run limit: if time runs out, commit WIP and list remaining items in the report.

## Context
LightVela AI reviewed P7 on 25/11 10:20 (repo public LangTieu/image-extraction-engine, main through e1489d0).
14 findings. Liaison independently verified findings 1–4 against the real code — ALL REAL:
- api.ts:32 `BASE = "/api/v1"` vs backend prefix `/v1` (settings.py:22, app.py:37) — UI fetches 404.
- api.ts:59 POST `.../jobs/{jobId}/review/{fileId}?action=` — no such route; only GET review (app.py:240) + PATCH fields (app.py:265).
- api.ts:63 `.../jobs/{jobId}/files/{fileId}/export/{fmt}` — real route is GET `/jobs/{job_id}/exports/{fmt}` (app.py:330).
- settings.py:41 empty key disables auth; CORS `*`; compose IMAGE_ENGINE_API_KEY commented out; deploy runs compose with 8000:8000.

## Fix (in severity order)
1. **CRITICAL — UI base path.** Make every UI fetch hit a real route. Prefer `BASE = "/v1"` (UI + API same origin in prod: StaticFiles serves UI at `/`, API at `/v1`). Fix the vite dev proxy to match (proxy `/v1`, or rewrite) so `npm run dev` works too.
2. **CRITICAL — Review action.** Wire Accept/Reject buttons to the real endpoint: PATCH `/v1/jobs/{job_id}/fields/{field_id}` with JSON body (field id, NOT file id). App.tsx:88-93.
3. **CRITICAL — Export links.** Point download links at the real route GET `/v1/jobs/{job_id}/exports/{fmt}`. Note the real endpoint is per-job (first file with that format, app.py:337-346) — if a per-file export is needed, add a per-file export endpoint; otherwise make the UI per-job. Decide the cleanest, document the choice.
4. **HIGH — Auth (DO NOT implement the gate in this round).** The public auth gate awaits Henrry's decision (asked 09:18 25/11). Do NOT change auth behaviour. Instead, in the report, write down exactly what the gate would need (key env + UI X-API-Key header + compose) so it is ready when he decides.
5. **HIGH — Timeout zombie threads.** `_process_file_with_timeout` (runner.py:87-105): a timed-out daemon thread must NOT later commit `completed` + results (runner.py:196-220) after the file was marked failed. Add a cancellation token/flag the late thread checks before committing; do not let timed-out threads accumulate silently.
6. **MEDIUM — Polling vs rate limit.** App.tsx polls listJobs every 3s + getJob every 1.5s = 60 req/min = the limit (settings.py:42), so the first upload/click gets 429. Fix by lowering poll frequency and/or raising/exempting read polling — one open tab + one upload must work without 429.
7. **MEDIUM — create_exports sync but 202.** app.py:317-327 runs build_exports inline while returning 202. Either make it truly async (background task + status) or return 200. Pick one, document it.
8. **MEDIUM — Deploy workflow.** deploy.yml: (a) trigger paths `service/**` misses Dockerfile/pyproject/engine changes — widen it; (b) add a concurrency group so two rapid pushes don't race on port 8000; (c) the GHCR image from build-push is never pulled/run — either deploy the GHCR image (pull + run) or drop build-push; (d) `pip install -e .` runs globally with no venv on the persistent self-hosted runner — use a venv. Keep the deploy working via lv3-runner (test job + deploy job + health loop must stay green).
9. **MEDIUM — Job status derivation.** `_refresh_job_status` (app.py:132-135): empty set `<= {"completed"}` is True, so a job with no files flips to completed; and it maps {failed, needs_review} → needs_review while runner.py:70-76 maps the same mix to failed. Unify the two state machines; empty set must NOT be completed.
10. **LOW — Orphaned uploads.** create_job (app.py:170-190): files written to disk before a later file raises 415/413; no job row survives but files are orphaned. Clean up already-written files on validation failure (or validate all files before writing any).
11. **LOW — Unbounded in-process state.** `_RATE` (app.py:67) entries never deleted; `CANCELLED` (runner.py:29) never cleared. Prune both. Also cap files per create_job request; do not read each upload fully into memory unboundedly (app.py:173).
12. **LOW — Dockerfile uses npm install, not npm ci.** Dockerfile:5 ignores the committed package-lock.json (copied line 4). Use `npm ci`.
13. **LOW — Container runs as root.** Add a non-root USER to the Dockerfile.
14. **LOW — /v1/jobs has no pagination.** Hard limit 100, no offset/cursor (app.py:200). Add offset/limit (or cursor) pagination.

## Tests (required — this is the regression that matters)
- Add a **UI–API contract test**: assert every fetch URL pattern used in `service/web/src/api.ts` matches a real backend route (method + path template). This test must FAIL on the old code and PASS after the fix.
- Add/extend API tests covering: review PATCH via UI-shaped call, export download URL, polling + upload under the rate limit, export endpoint status code, job status with zero files, orphaned-file cleanup on 415/413, pagination.
- If the guard denies creating new test files, write the FULL test file content into the report's fenced block and liaison will place it.

## Checks (NO pipes — log to file, read exit codes)
- `pytest -q` (exit 0), `ruff check .`, `mypy engine service benchmark` (0 errors), `python -m benchmark.validate` 35/35.
- Do NOT run the full benchmark; quick smoke only.

## Report
Write `P7_REVIEW_FIX_REPORT.md` in repo root: per finding — fixed or not, file:line of the fix, test evidence (test name + pass), and for finding 4 the exact gate plan. End with: remaining items (if any), and the exact commit hash on `p7-review-fix`.
