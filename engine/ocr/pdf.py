"""PDF text extraction: embedded text layer first, OCR for image-only pages.

Two extractors are provided:

* :class:`PdfiumTextLayer` — fast per-character boxes via pypdfium2.
* :class:`DoclingParser` — full Docling document parse (layout-aware,
  much heavier); used when the caller explicitly asks for it.

The orchestrator uses a page-level decision: a page whose text layer has
enough characters is text-native; otherwise the page is rasterized and sent
to the OCR path so scanned and mixed PDFs behave the same as images.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from engine.ocr.base import OCRToken


@dataclass
class PageText:
    page_index: int  # 0-based
    tokens: list[OCRToken] = field(default_factory=list)
    has_text_layer: bool = False
    render: np.ndarray | None = None  # RGB raster for the OCR path
    dpi: int = 200


class PdfiumTextLayer:
    """Extract per-character boxes from a PDF's embedded text layer."""

    name = "pypdfium2"

    def __init__(self, min_chars: int = 10) -> None:
        self.min_chars = min_chars

    def read(self, pdf_path: str, dpi: int = 200) -> list[PageText]:
        import pypdfium2 as pdfium

        out: list[PageText] = []
        doc = pdfium.PdfDocument(pdf_path)
        try:
            scale = dpi / 72.0
            for index, page in enumerate(doc):
                tokens: list[OCRToken] = []
                textpage = page.get_textpage()
                n = textpage.count_chars()
                for i in range(n):
                    text = textpage.get_text_range(i, 1)
                    if not text or text.isspace():
                        continue
                    left, bottom, right, top = textpage.get_charbox(i)
                    # PDF origin is bottom-left; convert to image coords.
                    y0, y1 = page.get_height() - top, page.get_height() - bottom
                    tokens.append(
                        OCRToken(
                            text=text,
                            bbox=(left * scale, y0 * scale, right * scale, y1 * scale),
                            confidence=1.0,
                            language=None,
                            page_index=index,
                            scale=scale,
                        )
                    )
                has_layer = len(tokens) >= self.min_chars
                if has_layer:
                    tokens = _merge_words(tokens)
                render = None
                if not has_layer:
                    bitmap = page.render(scale=scale)
                    render = np.asarray(bitmap.to_pil().convert("RGB"))
                out.append(
                    PageText(
                        page_index=index,
                        tokens=tokens,
                        has_text_layer=has_layer,
                        render=render,
                        dpi=dpi,
                    )
                )
        finally:
            doc.close()
        return out


class DoclingParser:
    """Optional Docling-backed parse producing plain text per page.

    Docling runs its own layout + table model; the text comes back without
    usable per-word bboxes, so blocks are returned bbox-free and the caller
    merges them with the text-layer tokens when coordinates matter.
    """

    def __init__(self) -> None:
        # Any: Docling is an optional dependency with no bundled types;
        # the converter is created lazily and used only via .convert().
        self._converter: Any = None  # lazy: Docling model download is heavy

    def parse(self, pdf_path: str) -> list[str]:
        if self._converter is None:
            from docling.document_converter import DocumentConverter

            self._converter = DocumentConverter()
        result = self._converter.convert(pdf_path)
        return [result.document.export_to_text()]


def _merge_words(tokens: list[OCRToken], gap_factor: float = 0.45) -> list[OCRToken]:
    """Merge per-character tokens into word tokens.

    Chars on the same baseline whose horizontal gap is below ``gap_factor``
    times the local char width are joined; lines are split on larger vertical
    jumps.
    """
    if not tokens:
        return tokens
    from engine.ocr.reading_order import group_lines

    words: list[OCRToken] = []
    for line in group_lines(tokens, overlap=0.5):
        chars = sorted(line, key=lambda t: t.bbox[0])
        cur: list[OCRToken] = [chars[0]]
        for ch in chars[1:]:
            prev = cur[-1]
            prev_w = max(prev.bbox[2] - prev.bbox[0], 1.0)
            gap = ch.bbox[0] - prev.bbox[2]
            if gap <= gap_factor * prev_w:
                cur.append(ch)
            else:
                words.append(_word_from(cur))
                cur = [ch]
        words.append(_word_from(cur))
    return words


def _word_from(chars: list[OCRToken]) -> OCRToken:
    return OCRToken(
        text="".join(c.text for c in chars),
        bbox=(
            min(c.bbox[0] for c in chars),
            min(c.bbox[1] for c in chars),
            max(c.bbox[2] for c in chars),
            max(c.bbox[3] for c in chars),
        ),
        confidence=min(c.confidence for c in chars),
        language=chars[0].language,
        page_index=chars[0].page_index,
        scale=chars[0].scale,
    )


def extract_pdf_pages(pdf_path: str, *, dpi: int = 200) -> list[PageText]:
    """Text-layer fast path with rasterized fallbacks for image-only pages."""
    return PdfiumTextLayer().read(pdf_path, dpi=dpi)
