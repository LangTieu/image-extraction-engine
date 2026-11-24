"""Debug visualization for table extraction (P3).

``render_debug`` draws cell grids, region bboxes and optional token boxes on
a copy of the image and returns it as BGR ``uint8`` (cv2 convention) so the
benchmark tools can ``imwrite`` it directly.
"""

from __future__ import annotations

import cv2
import numpy as np

from engine.ocr.base import OCRToken
from engine.tables.base import CellGrid

_REGION_COLOR = (0, 200, 0)  # green: table region
_CELL_COLOR = (0, 160, 255)  # orange: cell
_TOKEN_COLOR = (200, 0, 200)  # purple: assigned tokens
_HEADER_COLOR = (0, 0, 255)  # red: header row


def render_debug(
    image: np.ndarray,
    grids: list[CellGrid],
    *,
    tokens: list[OCRToken] | None = None,
    assign: dict[int, list[int]] | None = None,
) -> np.ndarray:
    """Draw grids/tokens on a copy of ``image`` (RGB or gray in, BGR out)."""
    if image.ndim == 2:
        canvas = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    else:
        canvas = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
    for grid in grids:
        x0, y0, x1, y1 = (int(v) for v in grid.region.bbox)
        cv2.rectangle(canvas, (x0, y0), (x1, y1), _REGION_COLOR, 2)
        cv2.putText(
            canvas,
            f"{grid.region.backend} {grid.region.score:.2f} {grid.n_rows}x{grid.n_cols}",
            (x0, max(12, y0 - 4)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.4,
            _REGION_COLOR,
            1,
        )
        for cell in grid.cells:
            cx0, cy0, cx1, cy1 = (int(v) for v in cell.bbox)
            color = _HEADER_COLOR if (grid.has_header and cell.row == 0) else _CELL_COLOR
            cv2.rectangle(canvas, (cx0, cy0), (cx1, cy1), color, 1)
    if tokens is not None:
        for token in tokens:
            tx0, ty0, tx1, ty1 = (int(v) for v in token.bbox)
            cv2.rectangle(canvas, (tx0, ty0), (tx1, ty1), _TOKEN_COLOR, 1)
    return canvas


__all__ = ["render_debug"]
