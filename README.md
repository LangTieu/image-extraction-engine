# Image Extraction Engine

Modular Hybrid Vision Engine — OCR, table extraction and industrial vision
(Vietnamese + English).

## Status

- P0 Requirements & data spec — done
- P1 Preprocessing — done
- P2 General OCR — done
- P3 Table extraction (ruled / borderless / hybrid / TATR) — done
- P4 Industrial Vision — next

## Layout

- `engine/` — schema, preprocessing, OCR, tables, router, metrics
- `benchmark/` — validator, evaluation scripts and results
- `docs/spec/` — specifications; `docs/reports/` — phase reports
- `tests/` — pytest suite (80 tests)

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
