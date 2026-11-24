"""Typed errors for the preprocessing stage.

Per docs/spec/inputs.md: corrupt or unsupported inputs produce typed errors,
never crashes.
"""

from __future__ import annotations


class PreprocessingError(Exception):
    """Base class for all preprocessing errors."""


class UnsupportedFormatError(PreprocessingError):
    """The file extension / container is not a supported input format."""


class CorruptImageError(PreprocessingError):
    """The file exists but cannot be decoded (truncated, wrong magic bytes...)."""


class InputLimitError(PreprocessingError):
    """The input exceeds a documented limit (file size, pixel size, pages)."""


class SourceNotFoundError(PreprocessingError):
    """The source path does not exist."""
