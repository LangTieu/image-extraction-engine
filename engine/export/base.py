"""Exporter interface, options and registry (P6).

Every exporter takes a validated :class:`ExtractionResult`, an output path
and :class:`ExportOptions`, writes one artifact and returns an
:class:`ExportArtifact` (path, MIME type, sha256 checksum). Failures raise
the typed :class:`ExportError`; the caller never sees a library exception.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from engine.schema.models import ExtractionResult


class ExportError(RuntimeError):
    """Raised when an exporter cannot produce its output."""

    def __init__(self, exporter: str, message: str) -> None:
        self.exporter = exporter
        super().__init__(f"[{exporter}] {message}")


@dataclass
class ExportArtifact:
    """One written file plus the metadata the manifest needs.

    ``extra_artifacts`` lists every *secondary* file the exporter wrote next
    to the primary artifact (CSV ``tableN.csv``/``_meta.csv`` sidecars, image
    field-crop files, ...). The batch manifest records one entry per artifact,
    primary and secondary alike, so no written file is untracked.
    """

    path: Path
    mime: str
    checksum: str  # sha256 hex of the file bytes
    extra_artifacts: list[ExportArtifact] = field(default_factory=list)


@dataclass
class ExportOptions:
    """Per-run knobs shared by the exporters (defaults = brief defaults)."""

    def __post_init__(self) -> None:
        if self.image_dir is not None and not isinstance(self.image_dir, Path):
            self.image_dir = Path(self.image_dir)

    # CSV
    csv_delimiter: str = ","
    csv_bom: bool = False  # utf-8-sig for Vietnamese Excel
    decimal_separator: str = "."
    csv_meta_sidecar: bool = False  # write <name>_meta.csv (confidence + trace)
    # JSON
    values_only: bool = False  # True: strip provenance (bbox/cells/validation)
    # Image previews
    image_dir: Path | None = None  # where to resolve result.source.file_name
    field_crops: bool = False  # also write per-field crop thumbnails
    # Chunks (NDJSON)
    chunk_max_chars: int = 1200  # hard cap per chunk text (D5)
    # Batch
    zip_bundle: bool = False  # bundle artifacts + manifest into a .zip


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifact(path: Path, mime: str) -> ExportArtifact:
    return ExportArtifact(path=path, mime=mime, checksum=sha256_of(path))


class Exporter(Protocol):
    """Structural interface implemented by every exporter."""

    name: str

    def export(
        self, result: ExtractionResult, out_path: Path | str, options: ExportOptions
    ) -> ExportArtifact:
        """Write the result to ``out_path`` and return the artifact written."""
        ...


EXPORTERS: dict[str, Exporter] = {}


def register(name: str, factory: Callable[[], Exporter]) -> None:
    """Instantiate and register an exporter under ``name``.

    Raises ``ValueError`` when ``name`` is already registered: a duplicate
    registration is almost certainly a bug (a module imported twice under
    different names, or a typo shadowing a built-in), so it must not be
    silently replaced.
    """
    if name in EXPORTERS:
        raise ValueError(f"exporter {name!r} is already registered")
    EXPORTERS[name] = factory()


def get_exporter(name: str) -> Exporter:
    try:
        return EXPORTERS[name]
    except KeyError:
        known = ", ".join(sorted(EXPORTERS)) or "(none registered)"
        msg = f"unknown exporter {name!r}; expected one of {known}"
        raise ExportError("registry", msg) from None


# Confidence bands shared by the image preview and XLSX colouring.
LOW_CONFIDENCE = 0.7


def conf_band(confidence: float | None) -> str:
    """green >= 0.8, yellow >= LOW_CONFIDENCE, red below / unknown."""
    if confidence is None:
        return "red"
    if confidence >= 0.8:
        return "green"
    if confidence >= LOW_CONFIDENCE:
        return "yellow"
    return "red"
