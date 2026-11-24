"""XLSX exporter: one sheet per table + Summary + Traceability sheets.

Formatting per brief P6: frozen header row, auto-filter, set column widths,
numbers stored as numbers (with a number format), units as a separate
column, low-confidence / needs-review cells coloured with a comment
explaining why.
"""

from __future__ import annotations

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
from engine.schema.models import ExtractionResult, Table

_FILL = {
    "red": PatternFill("solid", fgColor="FFC7CE"),
    "yellow": PatternFill("solid", fgColor="FFEB9C"),
    "green": None,
}
_NUM_FMT = {"float": "0.000", "int": "0"}


def _as_number(text: str | None, decimal: str) -> tuple[bool, float | int | str | None, str]:
    """Return (is_number, value, number_format). Never raises."""
    if text is None:
        return False, None, ""
    t = text.strip()
    if not t:
        return False, None, ""
    norm = t.replace(" ", "") if decimal == "." else t.replace(" ", "").replace(decimal, ".")
    try:
        v = float(norm)
    except ValueError:
        return False, None, ""
    if v.is_integer() and "." not in norm:
        return True, int(v), _NUM_FMT["int"]
    return True, v, _NUM_FMT["float"]


def _fill_cells(ws, table: Table, options: ExportOptions, header_row: int) -> None:
    """Overlay cell-level confidence colouring + comments on the grid."""
    for cell in table.cells:
        if cell.confidence is None and not cell.needs_review:
            continue
        if table.columns:
            row = header_row + cell.row_index + 1
        else:
            row = header_row + cell.row_index
        col = cell.col_index + 1
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
    if columns:
        ws.append(columns)
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = f"A1:{get_column_letter(len(columns))}1"
        for i, _c in enumerate(columns, start=1):
            letter = get_column_letter(i)
            width = max(len(str(c)) for c in columns) + 2
            ws.column_dimensions[letter].width = min(width, 40)
    if table.rows:
        for r in table.rows:
            out_row: list = []
            for v in r:
                is_num, num, _fmt = _as_number(v, options.decimal_separator)
                out_row.append(num if is_num else v)
            ws.append(out_row)
        if columns:
            for r_i in range(2, len(table.rows) + 2):
                for c_i in range(1, len(columns) + 1):
                    cell = ws.cell(row=r_i, column=c_i)
                    if isinstance(cell.value, float):
                        cell.number_format = _NUM_FMT["float"]
                    elif isinstance(cell.value, int):
                        cell.number_format = _NUM_FMT["int"]
    if table.cells:
        _fill_cells(ws, table, options, header_row)
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
        wb.save(out)
        return artifact(out, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def make():
    return XlsxExporter()
