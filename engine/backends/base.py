"""Input backend interface and registry.

Small Docling-inspired shape (``docling/backend/abstract_backend.py``):
backends declare the formats they support, answer validity/pagination
questions and load a file into :class:`engine.preprocessing.io.LoadedImage`
objects. The registry keys backends by extension and MIME type.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from engine.preprocessing.errors import UnsupportedFormatError
from engine.preprocessing.io import LoadedImage


class UnsupportedInputError(UnsupportedFormatError):
    """No registered backend handles this input format.

    Carries the offending extension/MIME type and the set of supported
    formats, so callers can build structured error responses.
    """

    def __init__(
        self,
        message: str,
        *,
        format: str,
        mime: str | None = None,
        supported: frozenset[str] = frozenset(),
    ) -> None:
        super().__init__(message)
        self.format = format
        self.mime = mime
        self.supported = supported


@runtime_checkable
class InputBackend(Protocol):
    """A loader for one or more input formats."""

    name: str

    def supported_formats(self) -> frozenset[str]:
        """Extensions and MIME types this backend handles (lowercase)."""
        ...

    def is_valid(self, path: Path) -> bool:
        """Whether this file can be opened by this backend."""
        ...

    def supports_pagination(self) -> bool:
        """Whether the format holds multiple pages."""
        ...

    def page_count(self, path: Path) -> int:
        """Number of pages in the file (1 for single-image formats)."""
        ...

    def load(self, path: Path, *, dpi: int) -> list[LoadedImage]:
        """Decode the file into one LoadedImage per page."""
        ...


_REGISTRY: list[InputBackend] = []


def register_backend(backend: InputBackend) -> None:
    """Add a backend to the registry (first match wins)."""
    _REGISTRY.append(backend)


def registered_backends() -> list[InputBackend]:
    return list(_REGISTRY)


def get_backend(path: Path, mime: str | None = None) -> InputBackend:
    """Resolve the backend for a file by extension, falling back to MIME.

    Raises :class:`UnsupportedInputError` with structured fields when no
    backend matches.
    """
    suffix = path.suffix.lower()
    for backend in _REGISTRY:
        formats = backend.supported_formats()
        if suffix and suffix in formats:
            return backend
    if mime:
        for backend in _REGISTRY:
            if mime.lower() in backend.supported_formats():
                return backend
    supported: set[str] = set()
    for backend in _REGISTRY:
        supported |= backend.supported_formats()
    label = mime if mime else suffix
    raise UnsupportedInputError(
        f"{path.name}: unsupported input {label!r}",
        format=suffix if mime is None else mime,
        mime=mime,
        supported=frozenset(supported),
    )
