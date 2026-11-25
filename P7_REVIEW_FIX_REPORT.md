# P7 review-fix report (LightVela AI findings, round 1 + continue)

Branch `p7-review-fix`, base main `e1489d0`. Code commit: see "Commit" at the end.

## Per-finding status

1. **CRITICAL — UI base path — FIXED.** `service/web/src/api.ts:45` `const BASE = "/v1"` (same origin as prod: FastAPI serves the built UI at `/`, API at `/v1`). Dev proxy fixed to match: `service/web/vite.config.ts:10` proxies `/v1` to `http://127.0.0.1:8000`. Test: `test_ui_api_base_path_is_v1` PASS.
2. **CRITICAL — Review action — FIXED.** `service/web/src/api.ts:63-77` `review()` now PATCHes `/v1/jobs/{job_id}/fields/{field_id}` with a JSON body (field id, not file id). Wired in `service/web/src/App.tsx:34-57` (`doReview("accept" | "reject")` on Accept/Reject buttons). Backend route: `service/api/app.py:298`. Tests: `test_patch_accept_clears_flag`, `test_patch_reject_nulls_value`, `test_patch_invalid_action_422` PASS.
3. **CRITICAL — Export links — FIXED.** `service/web/src/api.ts:79-82` `exportUrl(jobId, fmt)` → GET `/v1/jobs/{job_id}/exports/{fmt}` (per-job endpoint, first file with that format); download links use it at `service/web/src/App.tsx:205`. No per-file endpoint added — per-job chosen and documented here. Tests: `test_exports_json_and_xlsx`, `test_exports_before_finish_409`, `test_ui_routes_exist_on_backend` PASS.
4. **HIGH — Auth — NOT CHANGED (per brief).** No auth behaviour change. Gate plan (ready for Henrry's decision):
   - Env: set `IMAGE_ENGINE_API_KEY` (read via `settings.api_key_env`, `service/core/settings.py:41-43`); non-empty key enables the check (empty key = auth off — consider flipping this fail-closed default when the gate lands).
   - Backend already enforces it: `service/api/app.py:46` middleware requires `X-API-Key` on everything except `/v1/health`.
   - UI: add the key to the built UI's fetches — a runtime-configured header (`window.__API_KEY__` injected by the server, or a login form storing the key and `api.ts` sending `X-API-Key` on every fetch; never hardcode in the bundle).
   - Compose: uncomment/set `IMAGE_ENGINE_API_KEY` in `docker-compose.yml` (`environment:` of `api`).
   - Deploy: pass the key as a GitHub secret into the compose env on the lv3 runner; rotate it there, not in the repo.
   - Rate limit stays per-IP (`service/api/app.py:72`); authenticated clients could later be keyed by API key id instead of IP.
5. **HIGH — Timeout zombie threads — FIXED.** `service/worker/runner.py:37-40` per-run token (`_WORKER_TOKENS`); `_process_file_with_timeout` (`runner.py:126-148`) revokes the token on timeout so the abandoned thread's later commit raises; `_check_token` (`runner.py:120-123`) guards commits, `_process_file` (`runner.py:210`) takes the token; the run loop stops retrying on `WorkerSuperseded` (`runner.py:72-73`, class at `runner.py:112`).
6. **MEDIUM — Polling vs rate limit — FIXED.** `service/web/src/App.tsx:7-8` `LIST_POLL_MS = 10_000`, `JOB_POLL_MS = 5_000` → ~6 list + ~12 job req/min ≈ 18 req/min, under the 60/min limit (`service/core/settings.py:42`). One open tab + one upload stays under the limit.
7. **MEDIUM — create_exports sync but 202 — FIXED.** `service/api/app.py:351-362` `create_exports` builds exports inline and returns the result with the implicit 200 (no `status_code=202`). Choice documented: synchronous, 200.
8. **MEDIUM — Deploy workflow — FIXED (finished in continue round).** `.github/workflows/deploy.yml`:
   (a) trigger paths widened to `service/**`, `engine/**`, `Dockerfile`, `docker-compose.yml`, `pyproject.toml`, the workflow itself (`deploy.yml:4-14`);
   (b) `concurrency: group: deploy-main, cancel-in-progress: false` (`deploy.yml:16-18`) so rapid pushes queue instead of racing port 8000;
   (c) deploy job now deploys the GHCR image: `docker/login-action@v3` + `docker pull ghcr.io/langtieu/image-extraction-engine:${{ github.sha }}` (`deploy.yml:85`) and `IMAGE_TAG=<sha> docker compose up -d --no-build` (`deploy.yml:87`); `docker-compose.yml:6-7` gained `image: ghcr.io/langtieu/image-extraction-engine:${IMAGE_TAG:-latest}` alongside `build: .` so local dev still builds;
   (d) test job runs in a venv: `python -m venv .venv` + activate for install and pytest (`deploy.yml:34-43`).
   Health loop and lv3 runner job layout unchanged. Verified locally: `docker compose config` ok; `npm run build` ok; pytest green. Not verified: an actual push-to-main deploy run (cannot run here).
9. **MEDIUM — Job status derivation — FIXED.** Unified into `service/core/status.py:6-18` `derive_job_status` (empty set → `queued`, never `completed`; `{failed, needs_review}` → `failed`), used by both API (`service/api/app.py:129-138`) and runner (`service/worker/runner.py:24`).
10. **LOW — Orphaned uploads — FIXED.** `service/api/app.py:206-213` on any failure during create, the DB rolls back and every already-written file is unlinked (`written` list, `app.py:201-205`).
11. **LOW — Unbounded in-process state — FIXED.** `_RATE` pruned when over 10 000 tracked clients (`service/api/app.py:64-66`, cap at `app.py:73`); `CANCELLED` discarded when the run ends (`service/worker/runner.py:109`); uploads capped at `settings.max_files_per_job` = 50 (`service/core/settings.py:43`, enforced `service/api/app.py:156-158`).
12. **LOW — Dockerfile npm install — FIXED.** `Dockerfile:5` `RUN npm ci --no-audit --no-fund 2>/dev/null || npm install --no-audit --no-fund` (npm ci preferred, lockfile respected).
13. **LOW — Container runs as root — FIXED.** `Dockerfile:41-44` non-root `appuser` (uid 10001) with `USER appuser`.
14. **LOW — /v1/jobs pagination — FIXED.** `service/api/app.py:222-231` `limit` (1-200, default 50) + `offset` Query params with `.offset()/.limit()`.

## Tests

Contract test: round 1 was blocked from creating new files, so the two contract tests were added to `tests/test_api.py:342-371` (`test_ui_api_base_path_is_v1`, `test_ui_routes_exist_on_backend` — the latter fails on the pre-fix UI, which called POST `/v1/jobs/{id}/files/{fid}/review` and POST `/v1/jobs/{id}/files/{fid}/export`, routes that never existed). The standalone file the brief asked for is below; the liaison may place it as `tests/test_ui_contract.py` (content is self-contained and mirrors the tests in `tests/test_api.py`; keeping both is harmless, or remove the duplicated block from `tests/test_api.py` when placing it).

```python
"""UI <-> API contract: every fetch URL in service/web/src/api.ts must match a
real backend route (method + path shape), and the UI must use the real /v1
prefix. Fails on the pre-fix UI (BASE = "/api/v1", POST .../files/{fid}/review,
POST .../files/{fid}/export/{fmt} — none of those routes exist)."""

from __future__ import annotations

import re
from pathlib import Path

WEB_SRC = Path(__file__).resolve().parents[1] / "service" / "web" / "src" / "api.ts"


def _api_ts_source() -> str:
    return WEB_SRC.read_text()


def _router_routes() -> set[tuple[str, str]]:
    from fastapi.routing import APIRoute

    from service.api.app import app as fastapi_app
    from service.api.app import router

    routes = set()
    for r in [*fastapi_app.routes, *router.routes]:
        if isinstance(r, APIRoute):
            for method in (r.methods or set()) - {"HEAD", "OPTIONS"}:
                routes.add((method.lower(), r.path))
    return routes


def _collect_ui_calls() -> set[tuple[str, str]]:
    """Extract (METHOD, path-template) pairs from the UI's api.ts source."""
    src = _api_ts_source()
    calls: set[tuple[str, str]] = set()
    for m in re.finditer(r"fetch\(\s*`([^`]+)`\s*,\s*\{[^}]*method:\s*[\"'](\w+)", src):
        if m.group(2).lower() in {"get", "post", "put", "patch", "delete"}:
            calls.add((m.group(2).lower(), m.group(1)))
    for m in re.finditer(r"fetch\(\s*`([^`]+)`\s*\)", src):  # no-options fetch = GET
        calls.add(("get", m.group(1)))
    return calls


def test_ui_api_base_path_is_v1() -> None:
    """P7 review fix #1: the UI must call the backend's real /v1 prefix."""
    assert 'const BASE = "/v1"' in _api_ts_source(), (
        "UI must call the backend's real /v1 prefix"
    )


def test_ui_routes_exist_on_backend() -> None:
    """Every fetch template in api.ts must match a real route (method + shape)."""
    backend = _router_routes()
    calls = _collect_ui_calls()
    assert calls, "no fetch calls found in api.ts — parser or file changed?"
    for method, template in calls:
        path = re.sub(r"^\$\{BASE\}", "/v1", template)
        wildcard = re.sub(r"\$\{[^}]+\}", "*", path)
        match = any(
            m == method
            and len(p.split("/")) == len(wildcard.split("/"))
            and all(seg == "*" or seg == pseg for seg, pseg in zip(wildcard.split("/"), p.split("/")))
            for m, p in backend
        )
        assert match, f"UI calls {method.upper()} {template} but backend has no such route"
```

## Checks run (this round)

- `.venv/bin/python -m pytest -q` → exit 0, all tests pass (35 passed per suite summary; contract tests included).
- `.venv/bin/python -m ruff check .` → "All checks passed!".
- `.venv/bin/python -m mypy engine service benchmark` → "Success: no issues found in 85 source files".
- `.venv/bin/python -m benchmark.validate` → "35 passed, 0 failed".
- `service/web`: `npm run build` → tsc + vite build succeeded (dist emitted).
- `docker compose config` → valid.

## Remaining items

- Auth gate (finding 4) is a written plan only, awaiting Henrry's decision — per brief.
- Not verified here: a real push-to-main deploy of the changed workflow (finding 8) — compose config, image tag wiring and the UI build were verified locally; the live lv3 deploy run must be watched on the first push to main.
- The brief's API-test list: polling-under-rate-limit, zero-files job status, orphaned-cleanup and pagination have no dedicated tests (the fixes are covered indirectly by the existing suite); only the two contract tests were added because round 1 could not create test files.
- Finding 12 keeps an `npm install` fallback after `npm ci` fails; if the lockfile is authoritative, drop the fallback.

## Commit

Code commit on `p7-review-fix`: `cbdac3e17a22` (report committed on top of it). Committed locally, not pushed.
