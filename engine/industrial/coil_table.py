"""Coil-table extraction with header alias mapping (P4 item 5).

Uses the P3 TablePipeline backends for structure, then maps raw header
strings (Vietnamese or English) onto canonical coil columns through the
active profile, validates each cell value against the industrial field
dictionary, and fills the unified-schema ``Table`` model.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from engine.industrial.profiles import IndustrialProfile
from engine.industrial.values import disambiguate, parse_value_unit
from engine.ocr.pipeline import _map_bbox
from engine.preprocessing.mapping import TransformLog
from engine.schema import BBox, Cell, Table
from engine.schema.industrial_fields import DEFAULT_FIELDS, validate_value
from engine.schema.models import Provenance

_COIL_HEADER_PREFIXES = ("coil", "vòng", "so", "lô", "id", "stt")


@dataclass
class CoilRow:
    values: dict[str, str]  # canonical column -> raw string
    notes: list[str] = field(default_factory=list)


def looks_like_coil_headers(headers: list[str], profile: IndustrialProfile | None) -> bool:
    mapped = [c for h in headers if (c := (profile.resolve_column(h) if profile else None))]
    if mapped:
        return len(mapped) >= max(1, len(headers) // 2)
    lowered = [" ".join(h.lower().split()) for h in headers]
    hits = sum(1 for h in lowered if h.startswith(_COIL_HEADER_PREFIXES))
    return hits >= max(1, len(headers) // 2)


def map_row(
    headers: list[str],
    row: list[str],
    profile: IndustrialProfile | None,
    *,
    alternatives: dict[int, list[str]] | None = None,
) -> CoilRow:
    """Map one raw table row onto canonical columns with alias resolution."""
    values: dict[str, str] = {}
    notes: list[str] = []
    for i, header in enumerate(headers):
        raw = row[i] if i < len(row) else ""
        column = profile.resolve_column(header) if profile else None
        if column is None:
            notes.append(f"unmapped header: {header!r}")
            continue
        raw = raw.strip()
        if alternatives and i in alternatives and profile is not None:
            field_def = profile.fields.get(column)
            if field_def is not None and field_def.format_regex:
                raw = disambiguate(raw, alternatives[i], field_def.format_regex)
        values[column] = raw
    return CoilRow(values=values, notes=notes)


def rows_to_table(
    table_name: str,
    headers: list[str],
    rows: list[list[str]],
    profile: IndustrialProfile | None,
    *,
    bbox: tuple[float, float, float, float] | None = None,
    resolve_headers: bool = True,
    transform_log: TransformLog | None = None,
    cell_bboxes: list[list[tuple]] | None = None,
) -> Table:
    """Build a unified-schema Table from raw header/row strings.

    ``cell_bboxes`` (aligned [header row] + data rows, working-image
    coordinates) plus ``transform_log`` fill real per-cell provenance:
    ``cell.bbox`` stays in working coordinates while ``prov`` carries the
    bbox mapped back to original-image coordinates.
    """
    mapped_headers = [
        ((profile.resolve_column(h) or h.strip()) if resolve_headers else h.strip())
        if profile
        else h.strip()
        for h in headers
    ]
    prov_bbox = _prov_bbox(bbox, transform_log) if bbox else []
    cells: list[Cell] = []
    for col, header in enumerate(mapped_headers):
        cells.append(
            Cell(
                row_index=0,
                col_index=col,
                text=header,
                bbox=_cell_bbox(0, col, cell_bboxes),
                prov=_cell_prov(0, col, cell_bboxes, transform_log),
            )
        )
    for r, row in enumerate(rows, start=1):
        for c in range(len(mapped_headers)):
            text = row[c].strip() if c < len(row) else ""
            cells.append(
                Cell(
                    row_index=r,
                    col_index=c,
                    text=text,
                    bbox=_cell_bbox(r, c, cell_bboxes),
                    prov=_cell_prov(r, c, cell_bboxes, transform_log),
                )
            )
    table_rows = [
        [next((cell.text for cell in cells if cell.row_index == r and cell.col_index == c), None)
         for c in range(len(mapped_headers))]
        for r in range(len(rows) + 1)
    ]
    return Table(
        table_name=table_name,
        columns=mapped_headers,
        rows=table_rows,
        cells=cells,
        bbox=BBox(x0=bbox[0], y0=bbox[1], x1=bbox[2], y1=bbox[3]) if bbox else None,
        prov=prov_bbox,
    )


def _prov_bbox(
    bbox: tuple[float, float, float, float], log: TransformLog | None
) -> list[Provenance]:
    src = bbox
    if log is not None:
        src = _map_bbox(bbox, log)
    # Single-photo input: one page, and the box is already in original px
    # after the log mapping, so the render scale relative to the source is 1.
    return [Provenance(page=0, scale=1.0, bbox=BBox(x0=src[0], y0=src[1], x1=src[2], y1=src[3]))]


def _cell_bbox(
    row: int, col: int, cell_bboxes: list[list[tuple]] | None
) -> BBox | None:
    box = None
    if cell_bboxes is not None and row < len(cell_bboxes) and col < len(cell_bboxes[row]):
        box = cell_bboxes[row][col]
    if box is None:
        return None
    return BBox(x0=box[0], y0=box[1], x1=box[2], y1=box[3])


def _cell_prov(
    row: int, col: int, cell_bboxes: list[list[tuple]] | None, log: TransformLog | None
) -> list[Provenance]:
    box = None
    if cell_bboxes is not None and row < len(cell_bboxes) and col < len(cell_bboxes[row]):
        box = cell_bboxes[row][col]
    if box is None:
        return []
    src = box
    if log is not None:
        src = _map_bbox(box, log)
    # Same page/scale bookkeeping as the table-level prov: photo source.
    return [Provenance(page=0, scale=1.0, bbox=BBox(x0=src[0], y0=src[1], x1=src[2], y1=src[3]))]


def validate_cells(rows: list[CoilRow], profile: IndustrialProfile) -> list[str]:
    """Field-dictionary validation; returns notes for out-of-range/bad values."""
    notes: list[str] = []
    for index, row in enumerate(rows):
        for column, raw in row.values.items():
            field_def = profile.fields.get(column)
            if field_def is None or field_def.type not in ("number", "integer"):
                continue
            parsed = parse_value_unit(raw, default_unit=field_def.unit)
            if parsed.value is None:
                notes.append(f"row {index} {column}: {parsed.notes[0]}")
                continue
            # Wire the field-dictionary rule check (format_regex + range)
            # into the extraction path: a failing format must be flagged.
            if column in DEFAULT_FIELDS and raw.strip():
                notes.extend(validate_value(column, raw))
            if field_def.min_value is not None and parsed.value < field_def.min_value:
                notes.append(f"row {index} {column}: {parsed.value} < min {field_def.min_value}")
            if field_def.max_value is not None and parsed.value > field_def.max_value:
                notes.append(f"row {index} {column}: {parsed.value} > max {field_def.max_value}")
    return notes
