# P7 User Guide — API & Web UI

Run the service, upload images or PDFs, extract fields and tables, review
flagged values and download exports (XLSX / JSON / CSV / PDF).

## 1. Run

```bash
# from the repository root
.venv/bin/uvicorn service.api.app:app --reload --port 8000
```

- Web UI: http://localhost:8000/ (after `cd service/web && npm install && npm run build`)
- Swagger UI: http://localhost:8000/docs
- Health: `GET /v1/health`
- Version / external-API indicator: `GET /v1/version`

No external services are required by default: SQLite at
`service/data/service.db`, artifacts under `service/data/artifacts/`,
in-process worker thread.

### Configuration (env vars, prefix `SERVICE_`; copy `.env.example` to `.env`)

| Variable | Default | Meaning |
|----------|---------|---------|
| `SERVICE_DB_URL` | `sqlite:///./service/data/service.db` | SQLAlchemy URL (PostgreSQL works unchanged) |
| `SERVICE_PROFILE` | `industrial` | Extraction profile |
| `SERVICE_WORKER_MODE` | `inprocess` | `inprocess` or `rq` (Redis queue) |
| `SERVICE_REDIS_URL` | `redis://localhost:6379/0` | Redis for `rq` mode |
| `SERVICE_MAX_UPLOAD_MB` | `20` | Per-file upload limit |
| `SERVICE_ALLOWED_UPLOAD_TYPES` | png/jpeg/tiff/bmp/webp/pdf | Accepted MIME types |
| `IMAGE_ENGINE_API_KEY` | *(unset)* | When set, every `/v1` call needs `X-API-Key` (verified: unset = open access, set = 401 without the header, 200 with it; `/v1/health` stays open) |
| `SERVICE_RATE_LIMIT_PER_MINUTE` | `60` | Per-client-IP request budget (0 disables) |
| `SERVICE_RETENTION_DAYS` | `30` | Artifact retention (0 keeps forever) |
| `SERVICE_CORS_ORIGINS` | `*` | Comma-separated allowed origins |
| `SERVICE_EXTERNAL_VISION_APIS` | `false` | External vision API switch (reported by `/v1/version`) |

## 2. API (v1)

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/v1/jobs` | Upload 1..n files (`multipart/form-data`, field `files`); query: `profile`, `category` (force document category), `languages` (OCR, e.g. `vi+en`), `export_formats` (comma list). `202` → `job_id` |
| GET | `/v1/jobs` | Recent jobs with status/progress |
| GET | `/v1/jobs/{job_id}` | One job, per-file statuses and results |
| GET | `/v1/jobs/{job_id}/result` | Unified JSON result of every file |
| POST | `/v1/jobs/{job_id}/cancel` | Cancel a queued/running job |
| GET | `/v1/jobs/{job_id}/review` | Fields flagged for review (`field_id`, reasons) |
| PATCH | `/v1/jobs/{job_id}/fields/{field_id}` | Body `{"action":"accept"\|"correct"\|"reject","value":...}`; corrected values are re-validated against the industrial dictionary and every action lands in the audit log |
| POST | `/v1/jobs/{job_id}/exports` | Body `{"formats":["xlsx","json",...]}` — (re)build artifacts |
| GET | `/v1/jobs/{job_id}/exports/{format}` | Download `xlsx|csv|json|pdf` |
| GET | `/v1/profiles` | Available extraction profiles |
| GET | `/v1/health` · `/v1/version` | Liveness; engine version + external-API flag |

### curl walkthrough

```bash
curl -sF files=@benchmark/seed/industrial_hmi/images/industrial_hmi_001.png \
     'http://localhost:8000/v1/jobs?profile=industrial'
# -> {"job_id":"job_...","status":"queued","files":1}

curl -s http://localhost:8000/v1/jobs/job_...                  # poll until completed
curl -s http://localhost:8000/v1/jobs/job_.../result           # unified JSON
curl -s http://localhost:8000/v1/jobs/job_.../review           # flagged fields
curl -XPATCH http://localhost:8000/v1/jobs/job_.../fields/temperature \
     -H 'Content-Type: application/json' \
     -d '{"action":"correct","value":"87"}'
curl -sF formats='["xlsx","json"]' http://localhost:8000/v1/jobs/job_.../exports
curl -s http://localhost:8000/v1/jobs/job_.../exports/xlsx -o out.xlsx
```

Statuses: `queued → processing → completed | needs_review | failed`, per job
and per file. A failing file is retried (2 retries, 300 s per-file timeout)
and isolated: it never fails the whole job. Errors surface per file on
`GET /v1/jobs/{id}`.

## 3. Web UI (`service/web`, React + TypeScript + Vite)

- **Upload** one or more images/PDFs (header button).
- **Job list** (left) polls every 3 s; selected job polls every 1.5 s with a
  progress bar while processing; **Cancel** on running jobs.
- **File cards** show the extracted fields table (review-flagged rows are
  highlighted), per-file status and confidence.
- **Review controls**: Accept / Reject on flagged fields, per brief workflow.
- **Download** buttons for each produced export format.

```bash
cd service/web
npm install
npm run build     # -> service/web/dist, served by the API at /
npm run dev       # dev server with /v1 proxied to :8000
```

## 4. Docker

```bash
docker compose up --build       # http://localhost:8000
```

The image builds the web UI (node stage) and installs Tesseract `vie+eng`.
Data persists in the `iee-data` volume. Scaling out: set
`SERVICE_WORKER_MODE=rq`, `SERVICE_REDIS_URL`, `SERVICE_DB_URL` (Postgres) and
run the same image as `rq worker-pool iee`. `docker compose --profile redis up`
adds a Redis container.

## 5. CI/CD

`.github/workflows/deploy.yml` builds the multi-stage image (node → python
3.12-slim + Tesseract) and pushes to GHCR on `main` and `v*` tags.

## 6. Architecture

```
service/web (React+TS+Vite, static)  ──  fetch /v1
service/api/app.py (FastAPI)         ──  auth + rate limit + uploads → DB
service/worker/runner.py             ──  engine: preprocess → OCR → profile
                                     ──  → validate → export (xlsx/json/csv)
service/core/db.py                   ──  SQLAlchemy: jobs, job_files
engine/export/bytes_export.py        ──  in-memory exports (P6 reuse)
```
