# Image Extraction Engine — API + web UI + worker (P7)
FROM node:22-slim AS webbuild
WORKDIR /web
COPY service/web/package.json service/web/package-lock.json* ./
RUN npm ci --no-audit --no-fund 2>/dev/null || npm install --no-audit --no-fund
COPY service/web/ ./
RUN npm run build

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Tesseract (vie+eng) for the OCR backend; libglib/libgl for OpenCV.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       tesseract-ocr tesseract-ocr-vie tesseract-ocr-eng curl \
       libglib2.0-0 libgl1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml ./
COPY engine/ engine/
COPY service/ service/
COPY --from=webbuild /web/dist/ service/web/dist/

RUN pip install --no-deps . \
    && pip install "fastapi>=0.115" "uvicorn[standard]>=0.30" \
       "sqlalchemy>=2.0" "pydantic-settings>=2.0" "python-multipart>=0.0.9" \
       "pydantic>=2.5" "numpy>=1.26" "opencv-python-headless>=4.9" "pillow>=10.0" \
       "pypdfium2>=4.25" "pyyaml>=6.0" "openpyxl>=3.1" "jsonschema>=4.20" "reportlab>=4.0" \
       "pytesseract>=0.3.10"
# Not installed (optional, lazy imports inside engine code, engines degrade gracefully):
# paddleocr/paddlex (engine/ocr/paddle_backend.py), docling (engine/ocr/pdf.py),
# torch/transformers/timm (engine/tables/tatr.py). Install them at runtime only if
# those backends are needed.

# Non-root runtime user; /app/service/data is the writable volume (DB + artifacts).
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/service/data \
    && chown -R appuser:appuser /app/service/data /app/service/web
USER appuser

ENV SERVICE_DB_URL=sqlite:///./service/data/service.db
VOLUME ["/app/service/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD curl -sf http://localhost:8000/v1/health || exit 1

CMD ["uvicorn", "service.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
