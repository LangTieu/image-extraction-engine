# V0 UI Wire Report

Branch: `v0-ui-wire` (fresh from main `03034a0`). Zip: `v0-ui.zip`,
sha256 `8f5f0bb704135f9b822dfd1be6011895f73f0e5e04f28127d2bf1889a2d4021d` (200,510 bytes) — verified before extraction.

## What was done

1. **Replaced `service/web`** with the v0 UI source (`index.html`, `src/`, `tsconfig.json`),
   a new plain `vite.config.ts` (no mock plugin; optional `VITE_PROXY_API=1` dev proxy to a
   local uvicorn), and an npm-merged `package.json` (kept the repo's npm workflow and name
   `image-extraction-engine-web`, adopted v0's React 19 / Vite 8 / TS 5.7 toolchain and
   `tsc --noEmit && vite build` script). The zip's `dev/mock-api.ts`, `pnpm-lock.yaml` and
   `pnpm-workspace.yaml` were **not** copied; the old `dist/` was removed and rebuilt.
2. **WIRE fixes in `src/api.ts`** (the only file allowed to talk to the backend), traced against
   `service/api/app.py`, `engine/schema/models.py` and the live OpenAPI spec:
   - `BASE` is `"/v1"` (double quotes — asserted by `test_ui_api_base_path_is_v1`).
   - `POST /v1/jobs`: `profile`, `category` (not `forced_category`), `languages` and
     `export_formats` are FastAPI **Query** parameters → moved from FormData to the query
     string (comma-joined); only `files` stays multipart.
   - `GET /v1/jobs/{id}/result`: each file entry nests the payload under `result`
     (`document_type`, `fields`, `tables`, page size) → `normalizeResultFile` unwraps it.
   - Field/table keys per `engine/schema/models.py`: bbox is a `{x0,y0,x1,y1}` **object**
     (`normalizeBBox` already handled it), alternatives are **`proposals`** (plain strings),
     original value falls back to `raw_text`, tables use `table_name`/`columns` and cells
     carry `row_index`/`col_index`.
   - `GET /v1/profiles` returns `{profiles: [{name, category}], default}` → defaults marked
     from the top-level `default` key. `GET /v1/version` returns `engine` as the version key.
3. **Contract tests kept green by extending the parser** (`tests/test_api.py:_collect_ui_calls`
   only): v0 funnels calls through `requestJson(path, init)` → `fetch(BASE + path)`, so the
   parser now recovers (method, path) from `requestJson` call sites (`jsonBody(METHOD, ...)`
   for writes, `{signal}` init for GETs) and prepends the asserted `/v1` prefix for relative
   templates. The test assertions themselves are unchanged; `POST /v1/jobs` is exercised via
   the XHR call site regex as before.
4. Removed dev-only mock wiring from the build path (mock file not copied; `tsconfig.json`
   no longer includes a `dev/` folder).

## Checks (all run in this task, exit codes read from the runner)

| Check | Result |
| --- | --- |
| `npm install` (service/web) | exit 0, 0 vulnerabilities |
| `npm run build` (`tsc --noEmit` + `vite build`) | exit 0; dist 288.78 kB js / 18.74 kB css |
| `python -m pytest -q` (full suite) | exit 0 — 154 passed |
| `python -m ruff check .` | exit 0 — All checks passed |
| `python -m mypy engine benchmark tests` | exit 0 — no issues in 85 files |
| `python -m benchmark.harness --validate` | exit 0 |
| `grep -rIl "mock" service/web/dist/` | no matches (exit 1) |
| `grep -rIl "YOUR_API_KEY\|sk-\|secret" dist/` | one false positive: `mask-type`, an SVG attribute in React's vendored runtime — not a secret |
| `grep -rIc "localhost:8000\|127.0.0.1:8000" dist/assets/` | 0 occurrences |

## Notes

- Verified against a live server on 127.0.0.1:8000 (openapi.json, endpoint list); no jobs
  existed, so response normalizers were validated against the schema/code, not a live upload.
- Bundle has no hardcoded API host (same-origin `/v1`) and no secrets.
