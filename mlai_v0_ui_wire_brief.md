# Brief: wire the v0 UI into service/web (mlai)

Repo: `/root/image-extraction-engine`, branch `v0-ui-wire` fresh from main `03034a0`.
Do NOT push to main. Do NOT deploy. Commit on branch `v0-ui-wire` only; liaison merges + deploys.
30-minute per-run limit: if time runs out, commit WIP and list remaining items in the report.

## Context
v0 rebuilt the Image Extraction Engine web UI from the REAL backend contract (per Henrry's direction: v0 designs the UI from the backend). The zip is already on this machine: `/root/image-extraction-engine/v0-ui.zip` (sha256 `8f5f0bb704135f9b822dfd1be6011895f73f0e5e04f28127d2bf1889a2d4021d`, 200,510 bytes, v0 chat "Image extraction UI"). Verified by the liaison: `src/api.ts` has `BASE = '/v1'`, all 12 endpoints listed, plain Vite + React 19 + TypeScript, no Next.js, no routing library.
Main `03034a0` currently ships the mlai-patched UI in `service/web/` (it works, but v0's UI replaces it).

## Tasks
1. **Replace `service/web/` with the v0 UI.** Unzip `v0-ui.zip` to a temp dir, then move its `src/` (+ `index.html`, `tsconfig.json`, `vite.config.ts`) into `service/web/`, replacing the current UI files. Keep the existing project layout: FastAPI serves the built UI from StaticFiles at `/`, API at `/v1`.
2. **Package manager stays npm — do NOT switch to pnpm.** v0's `package.json` says `packageManager: pnpm` and ships `pnpm-lock.yaml` / `pnpm-workspace.yaml`. Discard those three; merge only the needed dependencies into the project's existing `service/web/package.json` (React 19, react-dom, vite, @vitejs/plugin-react, typescript + @types). Regenerate `package-lock.json` with `npm install` (the Dockerfile runs `npm ci`, so the lockfile must match). Do NOT use v0's `package.json` as-is.
3. **Remove dev-only and leftover bits.** Delete `dev/mock-api.ts` entirely (the prod build must contain NO mock code and NO `/api` paths) and simplify `vite.config.ts` to a plain Vite config: dev-only `/v1` proxy to `http://127.0.0.1:8000` (env-gated, off by default), NO `allowedHosts` preview hostname, NO mock plugin. Remove any `.next` leftover if present.
4. **Align the WIRE block with the REAL backend.** v0 guessed request/response key names in `src/api.ts` (WIRE block: multipart fields `files/profile/forced_category/languages/export_formats`, PATCH key `value`, exports key `formats`, bboxArray `'xyxy'`). The running API container is live on this machine — fetch the real contract from `http://127.0.0.1:8000/openapi.json` AND read `service/api/app.py` + `service/api/schemas.py` + the result JSON shape (fields, bbox format — confirm `[x0,y0,x1,y1]` vs xywh from the engine schema / a real `GET /v1/jobs/{id}/result`). Fix every WIRE entry that differs from the real backend. Do not guess: every key must be traced to the OpenAPI spec or the backend code.
5. **Source image in review.** No backend endpoint serves the original image. Keep v0's browser-kept-copy approach (the uploaded file's object URL) for the review view. Do NOT invent a new endpoint. Note in the report that a real image-serving endpoint is a follow-up backend change.
6. **Keep the contract tests green.** `tests/test_api.py` has `test_ui_api_base_path_is_v1` + `test_ui_routes_exist_on_backend` (they assert every fetch in `service/web/src/api.ts` matches a real backend route). They MUST pass against the new `api.ts`. If the new UI adds fetch calls, the tests must cover them (extend the tests in `tests/test_api.py` — do NOT create new test files; the guard denies it).

## Checks (NO pipes — log to file, read exit codes; the harness "check failed" after a pipe is a known false alarm when the exit code is 0)
- `cd service/web && npm install && npx tsc --noEmit && npm run build` (exit 0; dist emitted).
- `.venv/bin/python -m pytest -q -p no:warnings` (exit 0; expect 154 tests: 152 + 2 contract tests).
- `.venv/bin/python -m ruff check .`, `.venv/bin/python -m mypy engine service benchmark`, `python -m benchmark.validate` 35/35.
- Grep the built `service/web/dist/` output for `/api/v1` and `mock-api` — both must have ZERO hits (proves no broken base path and no mock code ships).
- Do NOT run the full benchmark. Do NOT visually verify in a browser (liaison does the live UI click-through after merge).

## Report
Write `V0_UI_WIRE_REPORT.md` in repo root: what was replaced, every WIRE alignment made (old → new + the backend source that proves it), the image approach, test evidence (test names + pass, dist grep results), and remaining items (incl. the image-endpoint follow-up and whether anything in the zip looked like it missed v0's last small fix — the v0 chat mentioned a fix on branch `v0/image-extraction-ui`; if the UI builds and passes but something feels missing, say so explicitly). End with the commit hash on `v0-ui-wire`.
