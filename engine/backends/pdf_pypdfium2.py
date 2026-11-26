"""pypdfium2 PDF backend: rasterize pages to RGB numpy arrays.

Body moved unchanged from ``engine/preprocessing/io.py:_from_pdf``; the
limits and error messages are identical.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from engine.preprocessing.errors import CorruptImageError, InputLimitError
from engine.preprocessing.io import (
    MAX_PDF_PAGES,
    MAX_PIXELS_PER_SIDE,
    LoadedImage,
    _sha256_of,
)


class PypdfiumPdfBackend:
    """Rasterize PDF pages with pypdfium2 at a configurable DPI."""

    name = "pypdfium2"

    def supported_formats(self) -> frozenset[str]:
        return frozenset({".pdf", "application/pdf"})

    def is_valid(self, path: Path) -> bool:
        import pypdfium2 as pdfium

        try:
            pdf = pdfium.PdfDocument(path)
        except Exception:  # noqa: BLE001 - pdfium raises assorted types
            return False
        pdf.close()
        return True

    def supports_pagination(self) -> bool:
        return True

    def page_count(self, path: Path) -> int:
        import pypdfium2 as pdfium

        try:
            pdf = pdfium.PdfDocument(path)
        except Exception as exc:  # noqa: BLE001 - pdfium raises assorted types
            raise CorruptImageError(f"{path.name}: cannot open PDF ({exc})") from exc
        try:
            return len(pdf)
        finally:
            pdf.close()

    def load(self, path: Path, *, dpi: int) -> list[LoadedImage]:
        import pypdfium2 as pdfium

        sha256 = _sha256_of(path)
        try:
            pdf = pdfium.PdfDocument(path)
        except Exception as exc:  # noqa: BLE001 - pdfium raises assorted types
            raise CorruptImageError(f"{path.name}: cannot open PDF ({exc})") from exc
        try:
            pages: list[LoadedImage] = []
            count = min(len(pdf), MAX_PDF_PAGES)
            if len(pdf) > MAX_PDF_PAGES:
                raise InputLimitError(
                    f"{path.name}: PDF has {len(pdf)} pages, limit is {MAX_PDF_PAGES}"
                )
            scale = dpi / 72.0
            for index in range(count):
                page = pdf[index]
                bitmap = page.render(scale=scale)
                pil = bitmap.to_pil().convert("RGB")
                if max(pil.size) > MAX_PIXELS_PER_SIDE:
                    raise InputLimitError(
                        f"{path.name}: page {index} renders to {pil.size}, "
                        f"limit is {MAX_PIXELS_PER_SIDE}px per side"
                    )
                pages.append(
                    LoadedImage(
                        data=np.asarray(pil, dtype=np.uint8),
                        sha256=sha256,
                        source_path=str(path),
                        format="pdf",
                        page=index,
                    )
                )
            return pages
        finally:
            pdf.close()
