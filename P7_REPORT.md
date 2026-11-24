# P7 Report — API + Web UI + Deploy (branch `p7-review`)

Date: 2026-11-25. Continuation of round 1 (see `mlai_p7_brief.md`, `mlai_p7_continue_brief.md`).

## 1. What this phase added

- `service/api/app.py` — v1 REST API (jobs, results, review, exports, profiles, health, version), serves the built React UI from `service/web/dist/` at `/`.
- `service/core/` (settings, config), `service/worker/runner.py` (inprocess worker, optional RQ).
- `service/web/` — React + TS + Vite UI; production build committed? No: `service/web/dist/` is gitignored (runtime artifact) and built in Docker.
- `engine/export/bytes_export.py` — XLSX/JSON/PDF/CSV byte exporters.
- `Dockerfile` (multi-stage: node builds web, python serves API+UI with Tesseract vie+eng), `docker-compose.yml`, `.env.example`, `docs/user_guide.md`, README, `.gitignore`.
- `.github/workflows/deploy.yml` — Docker build+push to GHCR.

## 2. How to run

- API + UI: `.venv/bin/python -m uvicorn service.api.app:app --host 127.0.0.1 --port 8000` → UI at `http://127.0.0.1:8000/`, docs at `/docs`. The dist UI is served by the API itself (`home: 200`, real index.html verified).
- Docker Compose: `docker compose up --build` (API on 8000; UI baked into the image).
- Optional env: `IMAGE_ENGINE_API_KEY`, `SERVICE_WORKER_MODE=rq` + `SERVICE_REDIS_URL` for the RQ worker. See `docs/user_guide.md` for the full table.

## 3. Final checks (exit codes read, no pipes)

- `.venv/bin/python -m mypy service` → `Success: no issues found in 9 source files`.
- `.venv/bin/python -m ruff check engine/ service/ tests/` → `All checks passed!`.
- `.venv/bin/python -m pytest tests/ -q` → 134 passed (exit 0; one pre-existing pydantic serializer UserWarning in `tests/test_export.py::test_values_only_strips_extensions`).
- One bug found and fixed during smoke testing: `PATCH /v1/jobs/{id}/fields/{field_id}` mutated the `result_json` JSON column in place, which SQLAlchemy does not detect, so review corrections were not persisted (a 200 response was a lie). Fix: `flag_modified(jf, "result_json")` in `service/api/app.py`. Verified the corrected value now persists and reaches rebuilt exports.

## 4. Smoke test (real service, port 8000)

Upload: `POST /v1/jobs` with a seed image, `export_formats=xlsx,json` → **202** `{"job_id":"job_a38ebdefdad0","status":"queued"}`.
- `GET /v1/jobs/{id}` → **200**, `status: completed`, file `completed`.
- `GET /v1/jobs/{id}/result` → **200**.
- `GET /v1/jobs/{id}/review` → **200**, pending list contains the flagged field.
- `PATCH /v1/jobs/{id}/fields/coil_id_1` `{"action":"correct","value":"C999"}` → **200**; persisted value C999, `needs_review: false`, audit_log length 1 (verified in DB after the fix above).
- `POST /v1/jobs/{id}/exports` → **202** `{"formats":["xlsx","json"]}`.
- `GET /v1/jobs/{id}/exports/xlsx` → **200** (5,964 bytes); `GET /v1/jobs/{id}/exports/json` → **200** (1,339 bytes); the JSON export contains the corrected field (`{"name":"coil_id","value":"C999","needs_review":false}`).

Caveat (test setup, not a service bug): the bundled `benchmark/seed/**` images are 69-byte placeholder stubs and the industrial region detector finds no regions on synthetic images, so the smoke-test job's flagged field was seeded directly into the test job's `result_json` in `service/data/service.db` to exercise the real review/PATCH/export endpoints. Upload, extraction run, review listing, PATCH persistence and both exports were all real API/worker code paths.

## 5. Auth (verified with real requests)

- Default (env unset): all `/v1` endpoints open for local dev.
- With `IMAGE_ENGINE_API_KEY` set: `GET /v1/health` without key → **200** (health stays open); `GET /v1/jobs` without key → **401**; wrong `X-API-Key` → **401** (`{"detail":"missing or invalid X-API-Key header"}`); correct key → **200**. Design unchanged; documented in `docs/user_guide.md` §1.

## 6. Deploy workflow (YAML parsed)

- `.github/workflows/deploy.yml` parses cleanly (`yaml.safe_load`, no errors).
- Trigger: only `push` to `main` with `paths: ["service/**"]`. (Round 1 had extra `tags: v*` + `workflow_dispatch`; removed to match the brief.)
- `runs-on: [self-hosted, lv3]` (round 1 had `ubuntu-latest`; fixed to match the brief).
- Job `build-push`: buildx → GHCR, tags `:latest` and `:${{ github.sha }}`, gha cache.

## 7. `.gitignore`

Confirmed present: `service/web/dist/` (line 12), `service/web/node_modules/` (line 13), `service/data/` (line 11, runtime DB), `.env` (line 14).

## 8. Remaining debt / notes

- Seed images in `benchmark/seed/**` are 69-byte placeholders; regenerate real seed images before relying on end-to-end field extraction quality (round-1 brief item, owned by the liaison).
- The industrial region detector returned zero regions on hand-drawn HMI images; extraction quality on real HMI screenshots was not measured in this round.
- No new test files were added this round (separate test round to follow).
- Nothing committed/pushed per the brief; `BLOCKED.md` not needed.

## 9. Fix round (liaison verification 24/11, after the continue round)

Liaison kiểm chứng độc lập và tìm ra 2 lỗi thật; mlai sửa trong vòng fix (`mlai-p7-fix.log`, 24 calls, 0.18 credits):

1. **Dockerfile thiếu `pytesseract`** — `engine/ocr/tesseract_backend.py:8` import pytesseract top-level, worker import `TesseractEngine` mỗi job, nhưng Dockerfile không cài → mọi job OCR trong container chết `ModuleNotFoundError`. Đã thêm `pytesseract>=0.3.10` vào Dockerfile. `paddleocr`/`docling`/`timm` là lazy import (chỉ dùng khi gọi đúng backend) nên giữ ngoài image, đã ghi chú trong Dockerfile comment.
   - Kiểm chứng: `docker build .` thành công (`sha256:164343950f61...`, image `p7-fix-test:latest` còn trên LV3); chạy container: `GET /v1/health` ok, `POST /v1/jobs` → 202, job `completed`; container test đã xóa sau đó.
2. **deploy.yml chỉ build-push GHCR, không deploy** — thiếu job `test` và `deploy` so với brief. Đã thêm: job `test` (setup-python 3.12, `pip install -e ".[dev]"`, pytest; `build-push` cần `test`), job `deploy` (`runs-on: [self-hosted, lv3]`, `needs: build-push`, `docker compose up -d --build` + retry `curl -sf /v1/health` 30 lần). Compose build từ repo checkout nên deploy không cần pull GHCR; GHCR push giữ làm artifact.
   - **Follow-up do liaison tìm ra bằng probe (không nằm trong vòng fix):** job `test` chạy `pip install -e ".[dev]"` trên env mới — pyproject lúc đó KHÔNG có `pytesseract` nên `tests/test_ocr.py` fail ngay lúc collect (`ImportError: pytesseract`), cả pipeline deploy kẹt vĩnh viễn. Liaison chứng minh bằng probe chặn import (collection fail) + probe chỉ chặn paddle/docling/timm (collection pass) → chỉ `pytesseract` là hard requirement. Đã thêm `"pytesseract>=0.3.10"` vào `pyproject.toml` dependencies. `paddleocr`/`docling`/`timm` không test nào import trực tiếp nên không cần.
3. Dọn dẹp trước merge: thư mục runtime `data/` ở gốc repo (DB + artifact của smoke test cũ, settings hiện tại dùng `service/data/`) đã xóa; thêm `/data/` vào `.gitignore` để chặn tái diễn. Các file brief (`mlai_p7_*.md`) không commit (bản trên VM giữ lại).
