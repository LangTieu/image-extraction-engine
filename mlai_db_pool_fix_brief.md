# Brief: fix DB connection-pool exhaustion (live API 500s) (mlai)

Repo: `/root/image-extraction-engine`, branch `db-pool-fix` fresh from main `03034a0`.
Do NOT push to main. Do NOT deploy. Do NOT touch `service/web/` or the `v0-ui-wire` branch (a separate UI wiring round lives there, commit `72e5278` — leave it alone). Commit on branch `db-pool-fix` only; liaison merges + deploys.
30-minute per-run limit: if time runs out, commit WIP and list remaining items in the report.

## Problem (verified live by the liaison, 25/11 ~11:2x)
The deployed API at https://ocr.aistockvn.com/ returns 500 on every DB endpoint after ~15 requests: `sqlalchemy.exc.TimeoutError: QueuePool limit of size 5 overflow 10 reached, connection timed out, timeout 30.00`. `GET /v1/jobs/{id}`, `GET /v1/jobs/{id}/review`, `GET /v1/jobs/{id}/exports/{fmt}` all 500; the UI's polling alone exhausts the pool in about a minute, and a job created via API stayed "Queued" (its worker thread could not get a connection either). `/v1/health` still returns ok because it does not touch the DB.
Root cause: **no SQLAlchemy session is ever closed — there are ZERO `.close()` calls in `service/`**. `service/core/db.py:89 get_session()` returns a fresh `Session` each call; every caller in `service/api/app.py` (10 call sites: `_job_or_404`, `_file_or_404`, `_job_out`, `_refresh_job_status`, endpoints) and `service/worker/runner.py` (4 call sites: `process_job` etc.) never closes it. Read-only endpoints never commit, so their transaction stays open and the connection stays checked out until cyclic GC happens to collect the session — under UI polling (~18 req/min) the leak outruns GC and the 15-connection pool exhausts.

## Tasks
1. **Give every session a guaranteed close.** Preferred shape: a FastAPI dependency with `yield` + `try/finally: session.close()` for the endpoints, and a `session_scope()` context manager (or equivalent try/finally) for `runner.py` and the helpers. Convert ALL call sites in `service/api/app.py` and `service/worker/runner.py`. Keep `expire_on_commit=False` and all endpoint behaviour/return shapes identical.
2. **Do not change the API contract.** Same routes, same request/response shapes, same status codes. The `tests/test_api.py` contract tests must keep passing unchanged.
3. **Regression test (REQUIRED — this bug shipped because no test exercised the real session path).** Add a test to the EXISTING `tests/test_api.py` (do NOT create a new test file — the guard denies it): create a job via the TestClient, then call `GET /v1/jobs` + `GET /v1/jobs/{job_id}` 30+ times in a row against the REAL session path (no session override) and assert every response is 200. Before the fix this test must fail with pool exhaustion (prove it by running the test against the pre-fix code first, or by reasoning + a quick manual reproduction); after the fix it must pass.
4. **Live proof on this machine.** Start the API locally (uvicorn on a test port, fresh SQLite file) and curl `GET /v1/jobs` + `GET /v1/jobs/{id}` 30 times in a loop — all must return 200 with no 500s. Record the loop result in the report. Do NOT touch the deployed container (liaison restarts/deploys after merge).

## Checks (NO pipes — log to file, read exit codes)
- `.venv/bin/python -m pytest -q -p no:warnings` (exit 0; expect 154 + the new regression test(s)).
- `.venv/bin/python -m ruff check .`, `.venv/bin/python -m mypy engine service benchmark`, `python -m benchmark.validate` 35/35.
- Do NOT run the full benchmark. Do NOT deploy.

## Report
Write `DB_POOL_FIX_REPORT.md` in repo root: the leak mechanism (which call sites, why read-only endpoints leak), what was changed (per-file), the regression test + its pre-fix failure evidence, the live 30-request loop result, and whether the stuck "Queued" job is explained by the same cause (worker thread starved of connections) or needs separate work. End with the commit hash on `db-pool-fix`.
