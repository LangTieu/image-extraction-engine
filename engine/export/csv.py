"""CSV exporter: one UTF-8 CSV per table, optional BOM, delimiter and decimal
separator configurable, optional ``*_meta.csv`` sidecar with confidence and
traceability per cell. Deterministic: same input → same bytes.

Data precedence (P6 fix): cells are the *live readings*, rows may be stale, so
when a table has cells they win: the grid starts from ``rows`` (when present)
and every cell overwrites its ``(row_index, col_index)`` position; with no
``rows`` the grid is built from cells alone. ``row_index=0`` is the first row
of ``rows`` — the first data row, because headers live in ``columns``.

Secondary files (``.tableN.csv`` and ``_meta.csv`` sidecars) are returned on
the artifact's ``extra_artifacts`` so the batch manifest tracks every file
written, not just the primary one.
"""

from __future__ import annotations

import csv
from pathlib import Path

from engine.export.base import ExportArtifact, ExportError, ExportOptions, artifact
from engine.schema.models import ExtractionResult, Table


def _table_rows(table: Table) -> list[list[str | None]]:
    grid = [list(r) for r in table.rows]
    if table.cells:
        for c in table.cells:
            r_i, c_i = c.row_index, c.col_index
            while len(grid) <= r_i:
                grid.append([])
            grid[r_i].extend([""] * (c_i + 1 - len(grid[r_i])))
            grid[r_i][c_i] = c.text or ""
        width = max(len(r) for r in grid)
        for r in grid:
            r.extend([""] * (width - len(r)))
    return grid


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
        extras: list[ExportArtifact] = []
        for i, table in enumerate(result.tables, start=1):
            path = out if i == 1 else out.with_name(f"{out.stem}.table{i}{out.suffix}")
            with path.open("w", newline="", encoding=encoding) as fh:
                w = csv.writer(fh, delimiter=options.csv_delimiter)
                if table.columns:
                    w.writerow(table.columns)
                w.writerows(_table_rows(table))
            if path != out:
                extras.append(artifact(path, "text/csv"))
            if options.csv_meta_sidecar:
                meta_path = path.with_name(f"{path.stem}_meta.csv")
                with meta_path.open("w", newline="", encoding=encoding) as fh:
                    csv.writer(fh, delimiter=options.csv_delimiter).writerows(
                        _meta_rows(table, table.table_name or f"table{i}", page)
                    )
                extras.append(artifact(meta_path, "text/csv"))
        art = artifact(out, "text/csv")
        art.extra_artifacts = extras
        return art


def make():
    return CsvExporter()
