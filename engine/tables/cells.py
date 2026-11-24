"""Assign OCR tokens to table cells and build schema ``Table`` objects.

The first row of a grid becomes the column header when the backend says the
grid has a header; every other row becomes a data row. A cell whose token
covers several columns carries ``col_span`` > 1.
"""

from __future__ import annotations

import numpy as np

from engine.ocr.base import OCRToken
from engine.schema import BBox, Cell, Table
from engine.tables.base import CellGrid


def _overlap(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    return ix * iy


def assign_tokens(cells: list, tokens: list[OCRToken]) -> dict[int, list[OCRToken]]:
    """Map cell index (into ``cells``) to tokens assigned to that cell.

    A token goes to the cell with the largest bbox overlap, so tokens that
    straddle a cell border land in the cell they mostly cover. Tokens fully
    outside every cell are dropped.
    """
    assignment: dict[int, list[OCRToken]] = {}
    for token in tokens:
        best_i, best_area = -1, 0.0
        for i, cell in enumerate(cells):
            area = _overlap(token.bbox, cell.bbox)
            if area > best_area:
                best_i, best_area = i, area
        if best_i >= 0:
            assignment.setdefault(best_i, []).append(token)
    return assignment


def normalize_column_key(name: str) -> str:
    """Stable column key: uppercase, non-alphanumerics to underscores.

    ``"Hot Coil No."`` -> ``HOT_COIL_NO``, matching the field dictionary.
    """
    out = []
    for ch in name.strip().upper():
        out.append(ch if ch.isalnum() else "_")
    key = "".join(out).strip("_")
    while "__" in key:
        key = key.replace("__", "_")
    return key


def grid_to_table(
    grid: CellGrid, tokens: list[OCRToken], *, table_name: str | None = None
) -> Table:
    """Fill the unified-schema Table from a cell grid plus its OCR tokens."""
    assignment = assign_tokens(grid.cells, tokens)

    def cell_text(i: int) -> tuple[str, float | None]:
        toks = assignment.get(i, [])
        if not toks:
            return "", None
        toks = sorted(toks, key=lambda t: (t.bbox[0], t.bbox[1]))
        text = " ".join(t.text for t in toks).strip()
        conf = float(np.mean([t.confidence for t in toks]))
        return text, conf

    header_texts: list[str] = []
    body: list[list[str | None]] = []
    cells_out: list[Cell] = []
    n_cols = grid.n_cols
    row_cells: dict[int, list[int]] = {}
    for i, cell in enumerate(grid.cells):
        row_cells.setdefault(cell.row, []).append(i)

    for r in range(grid.n_rows):
        row_vals: list[str | None] = [None] * n_cols
        for i in row_cells.get(r, []):
            cell = grid.cells[i]
            text, conf = cell_text(i)
            if cell.col < n_cols:
                row_vals[cell.col] = text if text else None
            cells_out.append(
                Cell(
                    row_index=cell.row,
                    col_index=cell.col,
                    row_span=cell.row_span,
                    col_span=cell.col_span,
                    bbox=BBox(**dict(zip(("x0", "y0", "x1", "y1"), cell.bbox))),
                    text=text or None,
                    confidence=conf,
                )
            )
        body.append(row_vals)

    columns: list[str] = []
    if grid.has_header and body:
        header_texts = [v if v is not None else f"column_{c}" for c, v in enumerate(body[0])]
        columns = header_texts
        body = body[1:]

    # Rectangular rows for the rows/columns export path.
    rows = [list(r) for r in body]
    return Table(
        table_name=table_name,
        columns=columns,
        rows=rows,
        cells=cells_out,
        bbox=BBox(**dict(zip(("x0", "y0", "x1", "y1"), grid.region.bbox))),
        confidence=grid.region.score,
    )


__all__ = ["assign_tokens", "grid_to_table", "normalize_column_key"]
