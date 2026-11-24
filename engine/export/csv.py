"""CSV exporter: one UTF-8 CSV per table, optional BOM, delimiter and decimal
separator configurable, optional ``*_meta.csv`` sidecar with confidence and
traceability per cell. Deterministic: same input → same bytes.
"""

from __future__ import annotations

import csv
from pathlib import Path

from engine.export.base import ExportArtifact, ExportError, ExportOptions, artifact
from engine.schema.models import ExtractionResult, Table


def _table_rows(table: Table) -> list[list[str | None]]:
    if table.rows:
        return [list(r) for r in table.rows]
    if table.cells:
        grid: dict[tuple[int, int], str] = {}
        for c in table.cells:
            grid[(c.row_index, c.col_index)] = c.text or ""
        n_cols = max((c for _, c in grid), default=-1) + 1
        n_rows = max((r for r, _ in grid), default=-1) + 1
        return [[grid.get((r, c), "") for c in range(n_cols)] for r in range(n_rows)]
    return []


def _meta_rows(table: Table, table_name: str, page) -> list[list]:
    rows: list[list] = [
        ["kind", "table", "ref", "value", "source_page", "bbox", "confidence", "needs_review"]
    ]
    for c in table.cells:
        rows.append([
            "cell", table_name, f"r{c.row_index}c{c.col_index}", c.text, page,
            str(c.bbox.model_dump()) if c.bbox else "", c.confidence, c.needs_review,
        ])
    if not table.cells:
        for r_i, r in enumerate(table.rows):
            for c_i, v in enumerate(r):
                rows.append([
                    "row_value", table_name, f"r{r_i}c{c_i}", v, page,
                    str(table.bbox.model_dump()) if table.bbox else "",
                    table.confidence, table.needs_review,
                ])
    return rows


class CsvExporter:
    name = "csv"

    def export(
        self, result: ExtractionResult, out_path: Path | str, options: ExportOptions | None = None
    ) -> ExportArtifact:
        options = options or ExportOptions()
        out = Path(out_path)
        if not result.tables:
            raise ExportError(self.name, f"no tables to export for {out.name!r}")
        if out.suffix.lower() != ".csv":
            raise ExportError(self.name, f"expected a .csv path, got {out.name!r}")
        out.parent.mkdir(parents=True, exist_ok=True)
        encoding = "utf-8-sig" if options.csv_bom else "utf-8"
        page = result.source.page if result.source else None
        for i, table in enumerate(result.tables, start=1):
            path = out if i == 1 else out.with_name(f"{out.stem}.table{i}{out.suffix}")
            with path.open("w", newline="", encoding=encoding) as fh:
                w = csv.writer(fh, delimiter=options.csv_delimiter)
                if table.columns:
                    w.writerow(table.columns)
                w.writerows(_table_rows(table))
            if options.csv_meta_sidecar:
                meta_path = path.with_name(f"{path.stem}_meta.csv")
                with meta_path.open("w", newline="", encoding=encoding) as fh:
                    csv.writer(fh, delimiter=options.csv_delimiter).writerows(
                        _meta_rows(table, table.table_name or f"table{i}", page)
                    )
        return artifact(out, "text/csv")


def make():
    return CsvExporter()
