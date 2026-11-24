"""In-memory export helpers (P7): export a result to bytes, no temp files left.

Additive on top of the P6 file-based exporters: they run inside a temporary
directory and the bytes are returned with the P6 checksum and MIME type so the
API can stream artifacts from memory or cache them on disk.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from engine.export import ExportOptions, get_exporter
from engine.schema.models import ExtractionResult


@dataclass
class ExportBlob:
    name: str  # exporter name, e.g. "xlsx"
    mime: str
    checksum: str  # sha256 hex, from the P6 exporter
    data: bytes


def export_to_bytes(
    result: ExtractionResult,
    exporter_name: str,
    options: ExportOptions | None = None,
    filename_stem: str = "result",
) -> ExportBlob:
    """Run one registered exporter and return its primary artifact bytes."""
    options = options or ExportOptions()
    ext = {"xlsx": "xlsx", "csv": "csv", "json": "json", "pdf": "pdf", "jpg": "jpg"}.get(
        exporter_name, exporter_name
    )
    with tempfile.TemporaryDirectory(prefix="iee_export_") as tmp:
        out_path = Path(tmp) / f"{filename_stem}.{ext}"
        artifact = get_exporter(exporter_name).export(result, out_path, options)
        return ExportBlob(
            name=exporter_name,
            mime=artifact.mime,
            checksum=artifact.checksum,
            data=out_path.read_bytes(),
        )
