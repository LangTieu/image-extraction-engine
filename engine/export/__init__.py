"""Export engine (P6): XLSX, CSV, JSON, image preview and PDF report exporters.

Importing this package registers the built-in exporters in
``engine.export.base.EXPORTERS``; use :func:`export_batch` for one-call
exports with a checksum manifest (and optional ZIP bundle).
"""

from engine.export.base import (
    EXPORTERS,
    ExportArtifact,
    Exporter,
    ExportError,
    ExportOptions,
    get_exporter,
    register,
)
from engine.export.batch import export_batch, write_manifest

__all__ = [
    "EXPORTERS",
    "ExportArtifact",
    "ExportError",
    "ExportOptions",
    "Exporter",
    "export_batch",
    "get_exporter",
    "register",
    "write_manifest",
]


def _register_builtin() -> None:
    from engine.export.chunks import make as chunks_make
    from engine.export.csv import make as csv_make
    from engine.export.image import make as image_make
    from engine.export.json_export import make as json_make
    from engine.export.pdf import make as pdf_make
    from engine.export.xlsx import make as xlsx_make

    register("chunks_jsonl", chunks_make)
    register("csv", csv_make)
    register("json", json_make)
    register("jpg", image_make)
    register("pdf", pdf_make)
    register("xlsx", xlsx_make)


_register_builtin()
