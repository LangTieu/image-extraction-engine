# Image Extraction Engine

Modular Hybrid Vision Engine — OCR, table extraction and industrial vision
(Vietnamese + English).

## Status

- P0 Requirements & data spec — done
- P1 Preprocessing — done
- P2 General OCR — done
- P3 Table extraction (ruled / borderless / hybrid / TATR) — done
- P4 Industrial Vision — done
- P5 Validation & review — done
- P6 Export (XLSX / CSV / JSON / preview / PDF / batch) — done
- P7 API & Web UI + Docker — done (see `docs/user_guide.md`)

## Service (P7)

FastAPI + web UI + worker on top of the engine:

```bash
.venv/bin/uvicorn service.api.app:app --port 8000   # API at /v1, docs at /docs
cd service/web && npm install && npm run build       # build the web UI (served at /)
docker compose up --build                            # or run the whole stack
```

Full walkthrough: `docs/user_guide.md`.

## Layout

- `engine/` — schema, preprocessing, OCR, tables, router, metrics, export
- `service/` — FastAPI app, SQLAlchemy persistence, worker (P7)
- `service/web/` — React + TypeScript + Vite front end (P7)
- `benchmark/` — validator, evaluation scripts and results
- `docs/spec/` — specifications; `docs/reports/` — phase reports
- `tests/` — pytest suite

## Run

```bash
uv sync
uv pip install --python .venv/bin/python paddleocr paddlepaddle pytesseract docling
.venv/bin/python -m pytest tests/ -q
.venv/bin/python benchmark/validate.py
```

Tesseract with Vietnamese data (`tesseract-ocr-vie`) is required for the
pytesseract backend. Table Transformer weights are downloaded on first use
into the local HuggingFace cache and are not part of this repo. External
vision APIs are off by default.
