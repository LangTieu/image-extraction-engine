"""Ruled-table structure backend (OpenCV, no models).

Finds tables by extracting horizontal and vertical ruling lines with
morphological operations, intersecting them into a lattice and turning the
lattice into a cell grid. Works only for tables that draw their lines; the
borderless backend covers the rest.
"""

from __future__ import annotations

import cv2
import numpy as np

from engine.tables.base import CellBox, CellGrid, TableBackend, TableConfig, TableRegion


def _line_mask(binary: np.ndarray, axis: int, kernel_len: int) -> np.ndarray:
    kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT, (kernel_len, 1) if axis == 0 else (1, kernel_len)
    )
    return cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)


def _cluster_positions(positions: np.ndarray, tol: float) -> list[tuple[float, float]]:
    """Merge 1-D positions into segments; returns [(start, end), ...]."""
    if positions.size == 0:
        return []
    order = np.argsort(positions)
    segments: list[list[float]] = [[float(positions[order[0]]), float(positions[order[0]])]]
    for p in positions[order[1:]]:
        p = float(p)
        if p - segments[-1][1] <= tol:
            segments[-1][1] = max(segments[-1][1], p)
        else:
            segments.append([p, p])
    return [(s, e) for s, e in segments]


class RuledGridBackend(TableBackend):
    """Detect ruled tables and cut them into cells along their line lattice."""

    name = "ruled"

    def __init__(self, config: TableConfig | None = None) -> None:
        self.config = config or TableConfig()

    def detect(self, image, tokens: list) -> list[CellGrid]:
        cfg = self.config
        gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
        binary = cv2.adaptiveThreshold(
            255 - gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 15, -2
        )
        h, w = binary.shape
        hmask = _line_mask(binary, 0, max(10, w // cfg.ruled_line_scale))
        vmask = _line_mask(binary, 1, max(10, h // cfg.ruled_line_scale))

        raw_h = cv2.HoughLinesP(
            hmask, 1, np.pi / 180, threshold=40, minLineLength=w // 6, maxLineGap=6
        )
        raw_v = cv2.HoughLinesP(
            vmask, 1, np.pi / 180, threshold=40, minLineLength=h // 8, maxLineGap=6
        )
        hlines = [] if raw_h is None else np.asarray(raw_h)
        vlines = [] if raw_v is None else np.asarray(raw_v)
        if len(hlines) == 0 or len(vlines) == 0:
            return []

        tol = max(3.0, w / 200)
        rows = _cluster_positions(np.array([min(ln[0][1], ln[0][3]) for ln in hlines]), tol)
        cols = _cluster_positions(np.array([min(ln[0][0], ln[0][2]) for ln in vlines]), tol)
        if len(rows) < 2 or len(cols) < 2:
            return []

        y_bounds = [(s + e) / 2 for s, e in rows]
        x_bounds = [(s + e) / 2 for s, e in cols]
        x0, x1 = min(x_bounds), max(x_bounds)
        y0, y1 = min(y_bounds), max(y_bounds)
        region = TableRegion(
            bbox=(x0, y0, x1, y1),
            score=min(1.0, (len(rows) * len(cols)) / 20.0),
            backend=self.name,
            ruled=True,
        )
        if region.score < cfg.min_region_score:
            return []

        cells: list[CellBox] = []
        for r in range(len(y_bounds) - 1):
            for c in range(len(x_bounds) - 1):
                cells.append(
                    CellBox(
                        row=r,
                        col=c,
                        bbox=(
                            x_bounds[c],
                            y_bounds[r],
                            x_bounds[c + 1],
                            y_bounds[r + 1],
                        ),
                    )
                )
        return [
            CellGrid(region=region, n_rows=len(y_bounds) - 1, n_cols=len(x_bounds) - 1, cells=cells)
        ]


__all__ = ["RuledGridBackend"]
