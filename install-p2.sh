#!/bin/bash
# Install P2 deps for Image Extraction Engine (liaison-run, IB4).
cd /data/home/image-extraction-engine
echo "=== apt: tesseract ==="
sudo apt-get update -qq
sudo apt-get install -y tesseract-ocr tesseract-ocr-vie
echo "=== pip: paddleocr/paddlepaddle/pytesseract/docling ==="
uv pip install --python .venv/bin/python paddleocr paddlepaddle pytesseract docling
echo "INSTALL-P2-DONE"
