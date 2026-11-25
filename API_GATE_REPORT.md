# API key gate — api-gate (report)

Henrry Chốt: BẬT cổng mật khẩu cho OCR API. Done on branch `api-gate`.

## What shipped

1. **Backend (already had the middleware, now wired + tested):**
   `service/api/app.py` rejects every `/v1` call with 401 unless the
   `X-API-Key` header matches `IMAGE_ENGINE_API_KEY` (rate-limited per the
   existing limiter). New test asserts both `GET /v1/version` and
   `GET /v1/jobs` return 401 without/wrong key and 200 with the right key
   (`tests/test_api.py::test_auth_missing_wrong_and_correct_key`).

2. **docker-compose.yml:** the `api` service now requires
   `IMAGE_ENGINE_API_KEY` (required interpolation, so `docker compose up`
   fails fast when the operator forgot to set it). Verified:
   `IMAGE_ENGINE_API_KEY=x IMAGE_TAG=latest docker compose config -q` → ok;
   without the var, compose exits with
   `required variable IMAGE_ENGINE_API_KEY is missing a value`.

3. **.github/workflows/deploy.yml:** the deploy step passes
   `IMAGE_ENGINE_API_KEY=${{ secrets.IMAGE_ENGINE_API_KEY }}` into compose.
   **Action needed from Henry:** add the `IMAGE_ENGINE_API_KEY` secret under
   Settings → Secrets and variables → Actions, then the same value goes into
   the web UI's unlock screen.

4. **Web UI (`service/web`):**
   - `src/api.ts`: key stored in `localStorage` under `iee_api_key`;
     `authHeaders()` attaches `X-API-Key` to every fetch; the upload XHR sets
     it too; a 401 clears the key and fires the `iee-auth-error` window event
     (`handleAuthFailure`).
   - `src/components/Unlock.tsx`: password-style unlock screen. "Unlock"
     verifies the key against `GET /v1/version` before storing it as valid;
     "Continue without a key" only passes when the server really has auth
     disabled (it re-runs `/v1/version` and reverts if 401).
   - `src/App.tsx`: app renders the unlock overlay on first open (no key)
     and again on any later 401; sidebar gets a "Sign out / change key"
     button when a key is stored.
   - `src/styles.css`: overlay + card styles; `npm run typecheck` clean;
     `npm run build` succeeds.

## Fail-before-fix proof

New tests written first, run against unmodified UI code:
`test_ui_sends_api_key_header` and `test_ui_handles_401_by_relocking` both
FAILED (`AssertionError: api.ts must keep the key in localStorage under
iee_api_key` / `... must special-case a 401 response`); they pass after the
change.

## Checks (this run)

- `.venv/bin/python -m pytest -q` → 165 tests, 0 failures, 0 errors (junit-parsed)
- `.venv/bin/python -m mypy engine benchmark tests` → Success: no issues found in 85 source files
- `npm run typecheck` (service/web) → clean
- `npm run build` → ✓ built
- `docker compose config` → invalid without the key (gate works), valid with it

## Not verified

- Browser walkthrough: the built-in Playwright browser check is not
  available on this computer (`No module named 'playwright'`); UI verified by
  tests, typecheck and production build only.
- Live deploy: needs the `IMAGE_ENGINE_API_KEY` Actions secret from Henry.
