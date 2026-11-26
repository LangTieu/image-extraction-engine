"""Input loader: decode images, rasterize PDFs, normalize to RGB, hash source.

Supported inputs (docs/spec/inputs.md): JPG, PNG, WEBP, PDF (rasterized page
by page at a configurable DPI, default 300) and screenshots (PNG/JPG).
Documented limit defaults from P0 (pending confirmation): 50 MB per file,
8000x8000 px, 100 PDF pages.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from engine.preprocessing.errors import (
    CorruptImageError,
    InputLimitError,
    SourceNotFoundError,
    UnsupportedFormatError,
)

Image.MAX_IMAGE_PIXELS = 256_000_000  # decompression-bomb guard, above our own limit

MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_PIXELS_PER_SIDE = 8000
MAX_PDF_PAGES = 100
DEFAULT_DPI = 300

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
PDF_EXTENSIONS = {".pdf"}


@dataclass
class LoadedImage:
    """A decoded input, normalized to an RGB uint8 numpy array."""

    data: np.ndarray  # HxWx3, uint8, RGB
    sha256: str  # hash of the source file bytes
    source_path: str
    format: str  # "jpg" | "png" | "webp" | "pdf"
    page: int | None  # PDF page index (0-based), None for plain images


def _sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _check_limits(path: Path, size_bytes: int) -> None:
    if size_bytes > MAX_FILE_BYTES:
        raise InputLimitError(f"{path.name}: file is {size_bytes} bytes, limit is {MAX_FILE_BYTES}")


def _from_pdf(path: Path, sha256: str, dpi: int) -> list[LoadedImage]:
    """Deprecated alias: load a PDF through the pypdfium2 backend."""
    from engine.backends import PypdfiumPdfBackend

    return PypdfiumPdfBackend().load(path, dpi=dpi)


def load_input(path: str | Path, dpi: int = DEFAULT_DPI) -> list[LoadedImage]:
    """Load one file into one LoadedImage per page (PDF) or a single image.

    Raises typed errors on missing, unsupported, oversized or corrupt inputs.
    """
    source = Path(path)
    if not source.exists():
        raise SourceNotFoundError(str(source))
    _check_limits(source, source.stat().st_size)

    from engine.backends import get_backend  # lazy: avoids a circular import

    return get_backend(source).load(source, dpi=dpi)
