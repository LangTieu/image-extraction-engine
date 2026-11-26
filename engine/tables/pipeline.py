"""Table extraction orchestrator (P3).

``TablePipeline.extract`` runs the configured backend over one image (plus
its OCR tokens), assigns tokens to cells and fills the unified-schema
``Table`` model. Multi-image documents go through ``merge_pages``, which
renames duplicate ``table_name`` values (``sheet1`` -> ``sheet1_p2``) so
exports never silently overwrite a sheet.

Coordinates follow the P2 convention: cells carry bboxes in processed-image
pixels; when a :class:`~engine.preprocessing.mapping.TransformLog` is
supplied, cell bboxes are also mapped back to the original image.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np

from engine.ocr.base import OCRToken
from engine.ocr.multiscale import reocr_low_confidence
from engine.schema import BBox, Provenance, Table
from engine.schema.models import ExtractionStatus
from engine.tables.base import (
    TABLE_BACKENDS,
    TableBackend,
    TableConfig,
)
from engine.tables.cells import grid_to_table, normalize_column_key
from engine.tables.hybrid import region_iou


@dataclass
class TableResult:
    tables: list[Table] = field(default_factory=list)
    backends_used: list[str] = field(default_factory=list)
    elapsed_ms: float = 0.0
    status: ExtractionStatus = ExtractionStatus.COMPLETED
    warnings: list[str] = field(default_factory=list)


def _make_backend(name: str, config: TableConfig) -> TableBackend:
    if name == "ruled":
        from engine.tables.ruled import RuledGridBackend

        return RuledGridBackend(config)
    if name == "borderless":
        from engine.tables.borderless import BorderlessClusterBackend

        return BorderlessClusterBackend(config)
    if name == "hybrid":
        from engine.tables.hybrid import HybridBackend

        return HybridBackend(config)
    if name == "tatr":
        from engine.models import ModelKey, default_factory, options_hash
        from engine.tables.tatr import TATRBackend

        # Share one TATRBackend per (model pair, config): weights are loaded
        # lazily by the backend and cached here, so concurrent pipelines and
        # sequential files reuse the loaded models instead of reloading.
        return default_factory.get(
            ModelKey(
                engine="tatr",
                variant=f"{config.tatr_detection_model}|{config.tatr_structure_model}",
                device="cpu",
                options_hash=options_hash(config),
            ),
            lambda: TATRBackend(config),
        )
    raise ValueError(f"unknown table backend: {name!r}; expected one of {TABLE_BACKENDS}")


def _map_bbox(bbox, log):
    if log is None:
        return None
    # Map all four corners and take the true axis-aligned bounding box: under
    # rotation/scale a TL/BR-only mapping can shrink the box.
    corners = np.array(
        [[bbox[0], bbox[1]], [bbox[2], bbox[1]], [bbox[2], bbox[3]], [bbox[0], bbox[3]]],
        dtype=float,
    )
    mapped = log.map_to_original(corners)
    xs, ys = mapped[:, 0], mapped[:, 1]
    return BBox(x0=float(xs.min()), y0=float(ys.min()), x1=float(xs.max()), y1=float(ys.max()))


class TablePipeline:
    """Extract tables from images with a selectable structure backend."""

    def __init__(self, config: TableConfig | None = None) -> None:
        self.config = config or TableConfig()
        if self.config.backend not in TABLE_BACKENDS:
            raise ValueError(
                f"unknown table backend: {self.config.backend!r}; expected one of {TABLE_BACKENDS}"
            )
        self.backend = _make_backend(self.config.backend, self.config)

    def extract(
        self,
        image: np.ndarray,
        tokens: list[OCRToken],
        *,
        transform_log=None,
        table_name: str | None = None,
    ) -> TableResult:
        start = time.perf_counter()
        grids = self.backend.detect(image, tokens)
        tables: list[Table] = []
        used: list[str] = []
        warnings: list[str] = []
        for grid in grids:
            if grid.region.backend not in used:
                used.append(grid.region.backend)
            table = grid_to_table(grid, tokens, table_name=table_name)
            if transform_log is not None and table.bbox is not None:
                # Convention (see engine/schema/models.py): ``bbox`` stays in
                # the producer's working-image coordinates; prov carries the
                # box mapped back to original-image coordinates.
                table.prov = [
                    Provenance(
                        bbox=_map_bbox(
                            (
                                table.bbox.x0,
                                table.bbox.y0,
                                table.bbox.x1,
                                table.bbox.y1,
                            ),
                            transform_log,
                        )
                    )
                ]
                for cell in table.cells:
                    if cell.bbox is not None:
                        cell.prov = [
                            Provenance(
                                bbox=_map_bbox(
                                    (cell.bbox.x0, cell.bbox.y0, cell.bbox.x1, cell.bbox.y1),
                                    transform_log,
                                )
                            )
                        ]
            if not table.columns:
                warnings.append(f"table {table_name or ''}: no header row found")
            tables.append(table)
        status = (
            ExtractionStatus.COMPLETED_WITH_WARNINGS
            if warnings
            else ExtractionStatus.COMPLETED
        )
        return TableResult(
            tables=tables,
            backends_used=used,
            elapsed_ms=(time.perf_counter() - start) * 1000.0,
            status=status,
            warnings=warnings,
        )


def merge_pages(results: list[TableResult]) -> list[Table]:
    """Concatenate tables across pages/images.

    Two rules:
    - duplicate ``table_name`` values get a ``_pN`` suffix (first keeps the
      bare name) so exports never overwrite a sheet;
    - a table whose columns match a previous table's columns (same
      normalized header keys) is a *continuation*: its data rows are
      appended to the earlier table instead of creating a new one.
    """
    seen: dict[str, int] = {}
    merged: list[Table] = []
    by_columns: dict[tuple[str, ...], Table] = {}
    for result in results:
        for table in result.tables:
            name = table.table_name or "table"
            key = tuple(normalize_column_key(c) for c in table.columns) if table.columns else ()
            continuation = by_columns.get(key) if key else None
            if continuation is not None and table.rows:
                continuation.rows.extend(table.rows)
                continue
            if key:
                by_columns.setdefault(key, table)
            count = seen.get(name, 0)
            seen[name] = count + 1
            if count:
                table.table_name = f"{name}_p{count + 1}"
            merged.append(table)
    return merged


def reocr_cells(
    image: np.ndarray,
    table: Table,
    engine,
    *,
    threshold: float = 0.6,
) -> list[str]:
    """Re-OCR low-confidence cell crops via the P2 multi-scale hook.

    Cell bboxes are in the same coordinates as ``image`` (call this before
    mapping back to original coordinates). Cells whose mean token confidence
    is below ``threshold`` are cropped, upscaled 2x and re-recognized with
    ``engine`` (an :class:`engine.ocr.base.OCREngine`). Returns the list of
    cell texts that were re-recognized (for warnings/debug).
    """
    retried: list[str] = []
    for cell in table.cells:
        if cell.confidence is None or cell.confidence >= threshold:
            continue
        if cell.bbox is None:
            continue
        x0, y0, x1, y1 = (int(v) for v in (cell.bbox.x0, cell.bbox.y0, cell.bbox.x1, cell.bbox.y1))
        if x1 - x0 < 4 or y1 - y0 < 4 or y1 > image.shape[0] or x1 > image.shape[1]:
            continue
        crop = image[max(0, y0) : y1, max(0, x0) : x1]
        try:
            result = engine.recognize(crop)
        except Exception:
            continue
        retry = reocr_low_confidence(crop, result, engine, threshold=threshold)
        texts = [t.text for t in retry.tokens]
        if texts:
            cell.text = " ".join(texts)
            cell.confidence = float(np.mean([t.confidence for t in retry.tokens]))
            retried.append(cell.text or "")
    return retried


def choose_backend(result: TableResult) -> TableResult:
    """Pick the single best backend per image when hybrid produced multiple.

    Currently the hybrid backend already reconciles; kept as an explicit
    hook so the report can state which backend served each image.
    """
    return result


__all__ = [
    "TablePipeline",
    "TableResult",
    "choose_backend",
    "merge_pages",
    "reocr_cells",
    "region_iou",
]
