"""Pillow image backend for JPG/PNG/WEBP inputs.

Body moved unchanged from the image half of ``engine/preprocessing/io.py:
load_input``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from engine.backends.base import UnsupportedInputError
from engine.preprocessing.errors import CorruptImageError, InputLimitError
from engine.preprocessing.io import MAX_PIXELS_PER_SIDE, LoadedImage, _sha256_of

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}

_MIME_BY_SUFFIX = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}

_FORMAT_BY_SUFFIX = {
    ".jpg": "jpg",
    ".jpeg": "jpg",
    ".png": "png",
    ".webp": "webp",
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
        """Actual frame count (multi-frame GIF/APNG), 1 for plain images.

        Raises :class:`CorruptImageError` for unreadable files;
        ``FileNotFoundError`` propagates unchanged for missing ones.
        """
        try:
            with Image.open(path) as handle:
                return getattr(handle, "n_frames", 1)
        except FileNotFoundError:
            raise
        except Exception as exc:  # noqa: BLE001 - Pillow raises assorted types
            raise CorruptImageError(f"{path.name}: cannot open image ({exc})") from exc

    def load(self, path: Path, *, dpi: int) -> list[LoadedImage]:
        suffix = path.suffix.lower()
        try:
            image_format = _FORMAT_BY_SUFFIX[suffix]
        except KeyError:
            raise UnsupportedInputError(
                f"{path.name}: unsupported image extension {suffix!r}",
                format=suffix,
                supported=frozenset(IMAGE_EXTENSIONS),
            ) from None
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
                format=image_format,
                page=None,
            )
        ]
