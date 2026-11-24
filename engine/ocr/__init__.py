"""General OCR (P2) — backends, reading order, PDF text layer, orchestrator."""

from engine.ocr.base import OCREngine, OCRResult, OCRToken, normalize_text
from engine.ocr.multiscale import reocr_low_confidence
from engine.ocr.paddle_backend import PaddleOCREngine
from engine.ocr.pdf import DoclingParser, PdfiumTextLayer, extract_pdf_pages
from engine.ocr.pipeline import GeneralOCR, OCRDocument
from engine.ocr.reading_order import TextBlock, blocks_to_text, tokens_to_blocks
from engine.ocr.tesseract_backend import TesseractEngine

__all__ = [
    "OCRResult",
    "OCRToken",
    "OCREngine",
    "normalize_text",
    "PaddleOCREngine",
    "TesseractEngine",
    "reocr_low_confidence",
    "TextBlock",
    "blocks_to_text",
    "tokens_to_blocks",
    "PdfiumTextLayer",
    "DoclingParser",
    "extract_pdf_pages",
    "GeneralOCR",
    "OCRDocument",
]
