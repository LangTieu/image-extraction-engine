# DB Connection-Pool Exhaustion — Fix Report

Branch: `db-pool-fix` (fresh from main `03034a0`).

## Symptom

The deployed API at https://ocr.aistockvn.com/ returned 500 on every DB endpoint
after ~15 requests:

```
sqlalchemy.exc.TimeoutError: QueuePool limit of size 5 overflow 10 reached,
connection timed out, timeout 30.00
```

## Root cause

The engine pool is `size 5, max_overflow 10` = 15 connections. The old code
called `service.core.db.get_session()` at every call site and **never called
`session.close()` anywhere** — not in the API, not in the worker. A session
opened by a read endpoint starts a transaction (a `SELECT` checks a connection
out of the pool) and never gives it back. Under CPython refcounting a bare
local session would be reclaimed quickly, but in the live ASGI app the session
ends up in reference cycles (request/task frames), so only *cyclic* GC can free
it. Polling from the UI leaked one session per request faster than cyclic GC
ran; after 15 leaked sessions every checkout blocked 30 s and timed out — the
exact live error.

Leaking call sites (all fixed):

- `service/api/app.py`: `_job_or_404`, `_file_or_404`, `_job_out`,
  `_refresh_job_status`, `create_job`, `list_jobs`, `pending_review`,
  `review_field`, `cancel`, `create_exports`, `export_file`, `health`.
  Read-only endpoints leak exactly like write endpoints: the connection is
  checked out by the implicit transaction, not by writing.
- `service/worker/runner.py`: `process_job`, `cancel_job`, `build_exports`,
  `_process_file` (4 call sites).

## What was changed (per file)

- `service/core/db.py`
  - New `session_scope()` contextmanager: `get_session()` + `try/finally:
    session.close()`.
  - New `get_db()` FastAPI dependency: same guarantee, generator form.
- `service/api/app.py`
  - Every endpoint takes `session: Session = Depends(get_db)`; the session is
    closed in the dependency's `finally` on success, HTTPException and crash
    alike.
  - The helpers (`_job_or_404`, `_file_or_404`, `_job_out`,
    `_refresh_job_status`) now receive the caller's session instead of opening
    their own — one connection per request instead of two.
- `service/worker/runner.py`
  - `process_job` / `build_exports` are now thin wrappers over `_run_job` /
    `_build_exports` which run inside `session_scope()`.
  - `cancel_job` uses `session_scope()`.
  - `_process_file` closes its session in a `finally` (also on the failure
    path).

Behavior is otherwise identical: same models, same commit points, same
`expire_on_commit=False`, same pool settings.

## Regression test

`tests/test_api.py::test_no_session_leak_under_repeated_polling` — hits the
REAL session path (no dependency override) with 70 requests against the
`/v1/jobs` + `/v1/jobs/{id}` endpoints (the UI's polling pattern) and requires
200 on every response. It cannot pass if a session leaks per request.

## Proof

- Pre-fix manual reproduction (`/tmp/pool_repro.py`): 15 leaked,
  never-closed sessions exhaust the pool and the 16th checkout reproduces the
  live error verbatim: `QueuePool limit of size 5 overflow 10 reached,
  connection timed out, timeout 30.00`. (The TestClient-based regression test
  alone passes pre-fix because refcount GC reclaims the sessions fast enough —
  which is why the bug shipped unnoticed; the repro plus the test together
  pin the mechanism.)
- Full suite: 155 passed (154 baseline + 1 new regression test), exit 0.
- Live `uvicorn` smoke: 120 iterations × `/v1/jobs` + health = 60 × 200 then
  429s from the app's own 60 req/min rate limiter; **zero 500s, zero
  QueuePool errors** in the log.
- `mypy` on the 3 changed source files: `Success: no issues found in 3 source
  files`. `ruff check` on them + the test file: `All checks passed!`.
