"""Input backend package: interface, registry and built-in backends."""

from __future__ import annotations

from engine.backends.base import (
    InputBackend,
    UnsupportedInputError,
    clear_registry,
    get_backend,
    register_backend,
    registered_backends,
    unregister_backend,
)
from engine.backends.image import PillowImageBackend
from engine.backends.pdf_pypdfium2 import PypdfiumPdfBackend

__all__ = [
    "InputBackend",
    "PillowImageBackend",
    "PypdfiumPdfBackend",
    "UnsupportedInputError",
    "clear_registry",
    "get_backend",
    "register_backend",
    "registered_backends",
    "unregister_backend",
]
