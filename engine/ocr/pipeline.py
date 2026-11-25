"""GeneralOCR orchestrator (P2).

Coordinates OCR backends over preprocessed images and PDFs:

* images: primary backend runs on the processed image; a token ROI below
  ``low_confidence`` is re-OCR'd multi-scale; empty primary output falls
  back to the next engine.
* PDFs: pages with a sufficient embedded text layer skip OCR (fast path);
  image-only pages are rasterized and go through the image path.

All token bboxes are reported in *processed-image* pixel coordinates; when a
:class:`~engine.preprocessing.mapping.TransformLog` is supplied, blocks also
carry bboxes mapped back to the original image (``bbox_original``).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np

from engine.ocr.base import OCREngine, OCRResult, OCRToken
from engine.ocr.multiscale import reocr_low_confidence
from engine.ocr.pdf import PageText, extract_pdf_pages
from engine.ocr.reading_order import TextBlock, blocks_to_text, tokens_to_blocks
from engine.schema.models import BBox, Provenance


def _map_bbox(bbox, log) -> tuple[float, float, float, float]:
    if log is None:
        return bbox
    corners = np.array([[bbox[0], bbox[1]], [bbox[2], bbox[3]]], dtype=float)
    mapped = log.map_to_original(corners)
    (ax0, ay0), (ax1, ay1) = mapped
    return (min(ax0, ax1), min(ay0, ay1), max(ax0, ax1), max(ay0, ay1))


@dataclass
class OCRDocument:
    pages: list[list[TextBlock]] = field(default_factory=list)
    tokens: list[OCRToken] = field(default_factory=list)  # flattened, processed coords
    engines_used: list[str] = field(default_factory=list)
    elapsed_ms: float = 0.0

    def text(self) -> str:
        parts: list[str] = []
        for page in self.pages:
            if page:
                parts.append(blocks_to_text(page))
        return "\n\n".join(parts)


class GeneralOCR:
    def __init__(
        self,
        engines: list[OCREngine],
        *,
        low_confidence: float = 0.6,
        dpi: int = 200,
    ) -> None:
        if not engines:
            raise ValueError("GeneralOCR needs at least one OCR engine")
        self.engines = engines
        self.low_confidence = low_confidence
        self.dpi = dpi

    # image path ---------------------------------------------------------
    def recognize_image(self, image: np.ndarray, *, transform_log=None) -> OCRDocument:
        t0 = time.perf_counter()
        result = self._run_chain(image)
        for t in result.tokens:
            # Single raster input: one page, rendered 1:1 (no PDF DPI scaling).
            t.page_index = 0
            t.scale = 1.0
        blocks = tokens_to_blocks(result.tokens)
        doc = OCRDocument(
            pages=[blocks],
            tokens=result.tokens,
            engines_used=[result.engine] if result.engine else [],
            elapsed_ms=(time.perf_counter() - t0) * 1000,
        )
        if transform_log is not None:
            doc = _with_original_coords(doc, transform_log)
        for page in doc.pages:
            _attach_prov(page)
        return doc

    def _run_chain(self, image: np.ndarray) -> OCRResult:
        primary = self.engines[0]
        result = primary.recognize(image, min_confidence=0.0)
        if result.tokens and any(t.confidence < self.low_confidence for t in result.tokens):
            result = reocr_low_confidence(image, result, primary, threshold=self.low_confidence)
        if not result.tokens and len(self.engines) > 1:
            for fallback in self.engines[1:]:
                fallback_result = fallback.recognize(image, min_confidence=0.0)
                if fallback_result.tokens:
                    return fallback_result
        return result

    # pdf path -----------------------------------------------------------
    def recognize_pdf(self, pdf_path: str, *, transform_log=None) -> OCRDocument:
        t0 = time.perf_counter()
        pages: list[list[TextBlock]] = []
        tokens: list[OCRToken] = []
        engines_used: list[str] = []
        page_texts: list[PageText] = extract_pdf_pages(pdf_path, dpi=self.dpi)
        for page in page_texts:
            if page.has_text_layer:
                blocks = tokens_to_blocks(page.tokens)
                tokens.extend(page.tokens)
            else:
                assert page.render is not None
                result = self._run_chain(page.render)
                for t in result.tokens:
                    t.page_index = page.page_index
                    t.scale = page.dpi / 72.0
                if result.engine and result.engine not in engines_used:
                    engines_used.append(result.engine)
                blocks = tokens_to_blocks(result.tokens)
                tokens.extend(result.tokens)
            pages.append(blocks)
        doc = OCRDocument(
            pages=pages,
            tokens=tokens,
            engines_used=engines_used,
            elapsed_ms=(time.perf_counter() - t0) * 1000,
        )
        if transform_log is not None:
            doc = _with_original_coords(doc, transform_log)
        for blocks_page in doc.pages:
            _attach_prov(blocks_page)
        return doc


def _with_original_coords(doc: OCRDocument, log) -> OCRDocument:
    """Attach bbox_original to every token and block via the TransformLog."""
    for page in doc.pages:
        for block in page:
            block.bbox_original = _map_bbox(block.bbox, log)
            for token in block.tokens:
                token.bbox_original = _map_bbox(token.bbox, log)
    for token in doc.tokens:
        token.bbox_original = _map_bbox(token.bbox, log)
    return doc


def _attach_prov(blocks: list[TextBlock]) -> None:
    """Fill each block's provenance from real source position (producer side).

    ``bbox_original`` wins (source coordinates) and falls back to the
    processed bbox when no TransformLog was supplied (identical geometry).
    """
    for block in blocks:
        if block.prov:
            continue
        src = block.bbox_original or block.bbox
        block.prov = [
            Provenance(
                page=block.page_index,
                bbox=BBox(x0=src[0], y0=src[1], x1=src[2], y1=src[3]),
                scale=block.scale,
            )
        ]
