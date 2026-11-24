"""Table extraction stage (P3).

Backends: ``ruled`` (OpenCV line lattice), ``borderless`` (OCR-token
clustering), ``hybrid`` (reconcile both; the default) and ``tatr`` (Table
Transformer, weights must already be in the local HF cache — never
downloaded at runtime, see BLOCKED.md).
"""

from engine.tables.base import (
    TABLE_BACKENDS,
    CellBox,
    CellGrid,
    TableBackend,
    TableBackendUnavailable,
    TableConfig,
    TableRegion,
)
from engine.tables.pipeline import TablePipeline, TableResult, merge_pages
from engine.tables.viz import render_debug

__all__ = [
    "TABLE_BACKENDS",
    "CellBox",
    "CellGrid",
    "TableBackend",
    "TableBackendUnavailable",
    "TableConfig",
    "TablePipeline",
    "TableRegion",
    "TableResult",
    "merge_pages",
    "render_debug",
]
