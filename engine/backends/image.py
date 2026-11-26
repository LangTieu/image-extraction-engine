"""Pillow image backend for JPG/PNG/WEBP inputs.

Body moved unchanged from the image half of ``engine/preprocessing/io.py:
load_input``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from engine.preprocessing.errors import CorruptImageError, InputLimitError
from engine.preprocessing.io import MAX_PIXELS_PER_SIDE, LoadedImage, _sha256_of

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}

_MIME_BY_SUFFIX = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


class PillowImageBackend:
    """Decode single-page raster images with Pillow."""

    name = "pillow"

    def supported_formats(self) -> frozenset[str]:
        return frozenset(IMAGE_EXTENSIONS | set(_MIME_BY_SUFFIX.values()))

    def is_valid(self, path: Path) -> bool:
        try:
            with Image.open(path) as handle:
                handle.load()
            return True
        except Exception:  # noqa: BLE001 - Pillow raises assorted types
            return False

    def supports_pagination(self) -> bool:
        return False

    def page_count(self, path: Path) -> int:
        return 1

    def load(self, path: Path, *, dpi: int) -> list[LoadedImage]:
        suffix = path.suffix.lower()
        sha256 = _sha256_of(path)
        try:
            with Image.open(path) as handle:
                handle.load()
                pil = handle.convert("RGB")
        except Exception as exc:  # noqa: BLE001 - Pillow raises assorted types
            raise CorruptImageError(f"{path.name}: cannot decode image ({exc})") from exc

        width, height = pil.size
        if max(width, height) > MAX_PIXELS_PER_SIDE:
            raise InputLimitError(
                f"{path.name}: image is {width}x{height}, limit is {MAX_PIXELS_PER_SIDE}px per side"
            )
        return [
            LoadedImage(
                data=np.asarray(pil, dtype=np.uint8),
                sha256=sha256,
                source_path=str(path),
                format="png" if suffix == ".png" else ("webp" if suffix == ".webp" else "jpg"),
                page=None,
            )
        ]
