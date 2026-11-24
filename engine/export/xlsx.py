"""XLSX exporter: one sheet per table + Summary + Traceability sheets.

Formatting per brief P6: frozen header row, auto-filter, set column widths,
numbers stored as numbers (with a number format), units as a separate
column, low-confidence / needs-review cells coloured with a comment
explaining why.

P6 fixes: only strict numeric literals are stored as numbers (whitespace
thousands, ``NaN``/``Inf``, exponents etc. stay text); table data uses the
same cells-over-rows grid as the CSV exporter (cells are the live readings);
cell fills are bounded to the data region so they never land on the header or
the footer block; workbook created/modified timestamps are fixed so the same
input produces byte-identical output.
"""

from __future__ import annotations

import io
import re
import zipfile
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import PatternFill
from openpyxl.utils import get_column_letter

from engine.export.base import (
    ExportArtifact,
    ExportError,
    ExportOptions,
    artifact,
    conf_band,
)
from engine.export.csv import _table_rows
from engine.schema.models import ExtractionResult, Table

_FILL = {
    "red": PatternFill("solid", fgColor="FFC7CE"),
    "yellow": PatternFill("solid", fgColor="FFEB9C"),
    "green": None,
}
_NUM_FMT = {"float": "0.000", "int": "0"}
_NUMBER_RE = re.compile(r"^[+-]?\d+(?:\.\d+)?$")


def _as_number(text: str | None, decimal: str) -> tuple[bool, float | int | str | None, str]:
    """Return (is_number, value, number_format). Never raises.

    Only strict numeric literals count: an optional sign, digits and one
    optional decimal separator (``.`` by default, otherwise ``decimal``).
    Whitespace thousands (``12 500``), exponents (``1e3``), ``NaN`` and
    ``Inf`` all stay text.
    """
    if text is None:
        return False, None, ""
    t = text.strip()
    if not t:
        return False, None, ""
    if decimal != "." and re.fullmatch(r"[+-]?\d{1,3}(?:\.\d{3})+", t):
        # vi-style thousands dots ("1.234" → 1234); a dot is only stripped
        # when every dot group has exactly three digits after it.
        t = t.replace(".", "")
    norm = t if decimal == "." else t.replace(decimal, ".")
    if not _NUMBER_RE.match(norm):
        return False, None, ""
    v = float(norm)
    if v.is_integer() and "." not in norm:
        return True, int(v), _NUM_FMT["int"]
    return True, v, _NUM_FMT["float"]


def _fill_cells(ws, table: Table, options: ExportOptions, header_row: int, grid) -> None:
    """Overlay cell-level confidence colouring + comments on the grid.

    Convention (documented, P6 fix): ``cell.row_index=0`` is the first row of
    the data grid — the first *data* row, because headers live in
    ``columns``. Fills are bounded to the data region (``grid``), so a stale
    or out-of-range row/col index can never colour the header row or the
    footer block.
    """
    for cell in table.cells:
        row = header_row + cell.row_index + (1 if table.columns else 0)
        col = cell.col_index + 1
        if cell.row_index >= len(grid) or col > len(grid[cell.row_index]):
            continue  # outside the data region: colour nothing rather than misplace
        if cell.confidence is None and not cell.needs_review:
            continue
        target = ws.cell(row=row, column=col)
        band = conf_band(cell.confidence if cell.confidence is not None else 0.0)
        if band != "green" or cell.needs_review:
            fill = _FILL["red" if cell.needs_review else band]
            if fill:
                target.fill = fill
            if cell.confidence is not None:
                reason = f"confidence={cell.confidence}"
            else:
                reason = "needs review"
            if cell.proposals:
                reason += "; proposals: " + "; ".join(cell.proposals)
            target.comment = Comment(reason, "export")


def _table_sheet(wb: Workbook, table: Table, name: str, options: ExportOptions) -> None:
    ws = wb.create_sheet(name)
    header_row = 1
    columns = list(table.columns)
    grid = _table_rows(table)  # same cells-over-rows precedence as the CSV exporter
    if columns:
        ws.append(columns)
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = f"A1:{get_column_letter(len(columns))}1"
        for i, _c in enumerate(columns, start=1):
            letter = get_column_letter(i)
            width = max(len(str(c)) for c in columns) + 2
            ws.column_dimensions[letter].width = min(width, 40)
    for r in grid:
        out_row: list = []
        for v in r:
            is_num, num, _fmt = _as_number(
                str(v) if v is not None else None, options.decimal_separator
            )
            out_row.append(num if is_num else v)
        ws.append(out_row)
    if columns:
        for r_i in range(2, len(grid) + 2):
            for c_i in range(1, len(columns) + 1):
                cell = ws.cell(row=r_i, column=c_i)
                if isinstance(cell.value, float):
                    cell.number_format = _NUM_FMT["float"]
                elif isinstance(cell.value, int):
                    cell.number_format = _NUM_FMT["int"]
    if table.cells:
        _fill_cells(ws, table, options, header_row, grid)
    spacer = ws.max_row + 1
    ws.cell(row=spacer + 1, column=1, value="confidence")
    ws.cell(row=spacer + 1, column=2, value=table.confidence)
    ws.cell(row=spacer + 2, column=1, value="needs_review")
    ws.cell(row=spacer + 2, column=2, value=table.needs_review)
    if table.bbox:
        ws.cell(row=spacer + 3, column=1, value="bbox")
        ws.cell(row=spacer + 3, column=2, value=str(table.bbox.model_dump()))


def _summary_sheet(wb: Workbook, result: ExtractionResult) -> None:
    ws = wb.create_sheet("Summary")
    rows = [
        ("document_type", result.document_type),
        ("extraction_status", str(result.extraction_status.value)),
        ("job_id", result.job_id or ""),
        ("source_file", result.source.file_name if result.source else ""),
        ("source_page", result.source.page if result.source else ""),
        ("tables", len(result.tables)),
        ("fields", len(result.fields)),
        ("warnings", "; ".join(result.warnings)),
        ("validation_issues", "; ".join(f"{v.severity}:{v.id}" for v in result.validation_results)),
    ]
    for k, v in rows:
        ws.append([k, v])
    ws.column_dimensions["A"].width = 20
    ws.column_dimensions["B"].width = 60


def _traceability_sheet(wb: Workbook, result: ExtractionResult) -> None:
    ws = wb.create_sheet("Traceability")
    header = [
        "kind", "table", "ref", "value", "source_page",
        "bbox", "confidence", "needs_review", "validation_issues",
    ]
    ws.append(header)
    page = result.source.page if result.source else None

    def row(kind, tname, ref, value, bbox, conf, review, issues):
        ws.append([
            kind, tname, ref, value, page,
            str(bbox.model_dump()) if bbox else "", conf, review, issues,
        ])

    for t in result.tables:
        for c in t.cells:
            ref = f"r{c.row_index}c{c.col_index}"
            issues = ";".join(i.id for i in c.validation_results)
            row(
                "cell", t.table_name or "", ref, c.text, c.bbox,
                c.confidence, c.needs_review, issues,
            )
        for r_i, r in enumerate(t.rows):
            for c_i, v in enumerate(r):
                ref = f"r{r_i}c{c_i}"
                row(
                    "row_value", t.table_name or "", ref, v, t.bbox,
                    t.confidence, t.needs_review, "",
                )
    for f in result.fields:
        bbox = f.bbox if f.bbox else (f.cell_ref.bbox if f.cell_ref else None)
        issues = ";".join(i.id for i in f.validation_results)
        row("field", "", f.name, f.value, bbox, f.confidence, f.needs_review, issues)
    widths = (
        ("A", 10), ("B", 14), ("C", 16), ("D", 30), ("E", 12),
        ("F", 28), ("G", 12), ("H", 13), ("I", 24),
    )
    for letter, width in widths:
        ws.column_dimensions[letter].width = width
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:I{ws.max_row}"


class XlsxExporter:
    name = "xlsx"

    def export(
        self, result: ExtractionResult, out_path: Path | str, options: ExportOptions | None = None
    ) -> ExportArtifact:
        options = options or ExportOptions()
        out = Path(out_path)
        if out.suffix.lower() != ".xlsx":
            raise ExportError(self.name, f"expected a .xlsx path, got {out.name!r}")
        wb = Workbook()
        wb.properties.created = wb.properties.modified = datetime(1980, 1, 1, 0, 0, 0)
        wb.remove(wb.active)
        seen: dict[str, int] = {}
        for table in result.tables:
            base = (table.table_name or "table").replace("/", "_")[:28] or "table"
            n = seen.get(base, 0) + 1
            seen[base] = n
            _table_sheet(wb, table, base if n == 1 else f"{base}_{n}", options)
        _summary_sheet(wb, result)
        _traceability_sheet(wb, result)
        if not wb.sheetnames:
            wb.create_sheet("empty")
        out.parent.mkdir(parents=True, exist_ok=True)
        buf = io.BytesIO()
        wb.save(buf)
        # openpyxl stamps zip entries with the current time; rewrite them with
        # a fixed timestamp so the same input gives byte-identical output.
        with zipfile.ZipFile(buf) as src, zipfile.ZipFile(
            out, "w", zipfile.ZIP_DEFLATED
        ) as dst:
            for info in src.infolist():
                data = src.read(info.filename)
                if info.filename == "docProps/core.xml":
                    # openpyxl overwrites wb.properties.modified with now()
                    # on save, so pin the text content for determinism; keep
                    # the element's attributes (xmlns:dcterms, xsi:type) or
                    # the XML cannot be reopened.
                    data = re.sub(
                        rb"(<dcterms:modified[^>]*>)[^<]*(</dcterms:modified>)",
                        rb"\g<1>1980-01-01T00:00:00Z\g<2>",
                        data,
                    )
                fixed = zipfile.ZipInfo(info.filename, date_time=(1980, 1, 1, 0, 0, 0))
                fixed.compress_type = info.compress_type
                dst.writestr(fixed, data)
        return artifact(out, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def make():
    return XlsxExporter()
