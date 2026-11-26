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
_DEFAULTS_LOADED = False


def _ensure_defaults() -> None:
    """Register the built-in backends once, on first use.

    Lazy so that importing ``engine.backends.base`` directly (instead of the
    package) still ends up with a usable registry, and so custom backends
    registered before the first ``get_backend()`` call keep first-match
    priority over the defaults.
    """
    global _DEFAULTS_LOADED

    from engine.backends.image import PillowImageBackend
    from engine.backends.pdf_pypdfium2 import PypdfiumPdfBackend

    if _DEFAULTS_LOADED:
        return
    _REGISTRY.extend((PillowImageBackend(), PypdfiumPdfBackend()))
    _DEFAULTS_LOADED = True


def register_backend(backend: InputBackend) -> None:
    """Add a backend to the registry.

    The backend must satisfy the :class:`InputBackend` protocol. A backend
    whose ``name`` is already registered replaces the earlier entry;
    otherwise the backend is prepended, so a newly registered backend takes
    first-match priority over previously registered ones.
    """
    if not isinstance(backend, InputBackend):
        raise TypeError(f"{backend!r} does not satisfy the InputBackend protocol")
    for index, existing in enumerate(_REGISTRY):
        if existing.name == backend.name:
            _REGISTRY[index] = backend
            return
    _REGISTRY.insert(0, backend)


def unregister_backend(name: str) -> bool:
    """Remove the backend with this ``name``; True when one was removed."""
    for index, existing in enumerate(_REGISTRY):
        if existing.name == name:
            del _REGISTRY[index]
            return True
    return False


def clear_registry() -> None:
    """Drop every registered backend (test helper; nothing re-registers automatically)."""
    _REGISTRY.clear()


def registered_backends() -> list[InputBackend]:
    _ensure_defaults()
    return list(_REGISTRY)


def get_backend(path: Path, mime: str | None = None) -> InputBackend:
    """Resolve the backend for a file by extension, falling back to MIME.

    Precedence is documented as: a known extension always wins; the MIME
    type is only consulted for extension-less paths (no caller passes it
    today). MIME parameters (``application/pdf; charset=...``) are stripped
    before matching, and matching is case-insensitive.

    Raises :class:`UnsupportedInputError` with structured fields when no
    backend matches; ``format`` on the error is always the extension when
    the path has one (empty otherwise, in which case it carries the MIME).
    """
    _ensure_defaults()
    suffix = path.suffix.lower()
    clean_mime = mime.split(";", 1)[0].strip().lower() if mime else None
    for backend in _REGISTRY:
        formats = backend.supported_formats()
        if suffix and suffix in formats:
            return backend
    if clean_mime:
        for backend in _REGISTRY:
            if clean_mime in backend.supported_formats():
                return backend
    supported: set[str] = set()
    for backend in _REGISTRY:
        supported |= backend.supported_formats()
    raise UnsupportedInputError(
        f"{path.name}: unsupported input {(clean_mime or suffix)!r}",
        format=suffix if suffix else (clean_mime or ""),
        mime=clean_mime,
        supported=frozenset(supported),
    )
