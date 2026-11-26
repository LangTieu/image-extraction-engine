"""Input backend package: interface, registry and built-in backends."""

from __future__ import annotations

from engine.backends.base import (
    InputBackend,
    UnsupportedInputError,
    get_backend,
    register_backend,
    registered_backends,
)
from engine.backends.image import PillowImageBackend
from engine.backends.pdf_pypdfium2 import PypdfiumPdfBackend

__all__ = [
    "InputBackend",
    "PillowImageBackend",
    "PypdfiumPdfBackend",
    "UnsupportedInputError",
    "get_backend",
    "register_backend",
    "registered_backends",
]


def _register_defaults() -> None:
    from engine.backends.base import registered_backends

    if not registered_backends():
        register_backend(PypdfiumPdfBackend())
        register_backend(PillowImageBackend())


_register_defaults()
