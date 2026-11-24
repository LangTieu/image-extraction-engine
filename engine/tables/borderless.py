"""Borderless-table structure backend: cluster OCR tokens into a grid.

No images and no models: rows come from clustering token vertical centers,
columns from clustering horizontal edges. A gap larger than
``gap_factor *`` the local median gap splits a row/column, which handles
aligned text without ruling lines.
"""

from __future__ import annotations

import numpy as np

from engine.tables.base import CellBox, CellGrid, TableBackend, TableConfig, TableRegion


def _cluster_1d(values: np.ndarray, tol: float) -> list[list[float]]:
    """Group sorted values while consecutive gaps stay under ``tol``."""
    if values.size == 0:
        return []
    order = np.argsort(values)
    groups: list[list[float]] = [[float(values[order[0]])]]
    for v in values[order[1:]]:
        v = float(v)
        if v - max(groups[-1]) <= tol:
            groups[-1].append(v)
        else:
            groups.append([v])
    return groups


def _boundaries(groups: list[list[float]], coords: np.ndarray, lo: float, hi: float) -> list[float]:
    """Turn value clusters into split boundaries covering [lo, hi]."""
    bounds = [lo]
    for a, b in zip(groups[:-1], groups[1:]):
        bounds.append((max(a) + min(b)) / 2)
    bounds.append(hi)
    return bounds


class BorderlessClusterBackend(TableBackend):
    """Build a table grid from OCR token alignment alone."""

    name = "borderless"

    def __init__(self, config: TableConfig | None = None) -> None:
        self.config = config or TableConfig()

    def detect(self, image, tokens: list) -> list[CellGrid]:
        if len(tokens) < 4:
            return []
        cfg = self.config
        xs0 = np.array([t.bbox[0] for t in tokens])
        xs1 = np.array([t.bbox[2] for t in tokens])
        ys0 = np.array([t.bbox[1] for t in tokens])
        ys1 = np.array([t.bbox[3] for t in tokens])
        centers_y = (ys0 + ys1) / 2
        height_med = float(np.median(ys1 - ys0)) or 1.0

        row_tol = max(3.0, cfg.cluster_gap_factor * height_med)
        row_groups = _cluster_1d(centers_y, row_tol)
        if len(row_groups) < 2:
            return []

        x_lo, x_hi = float(xs0.min()), float(xs1.max())
        y_lo, y_hi = float(ys0.min()), float(ys1.max())
        region = TableRegion(
            bbox=(x_lo, y_lo, x_hi, y_hi),
            score=min(1.0, len(tokens) / 12.0),
            backend=self.name,
            ruled=False,
        )
        if region.score < cfg.min_region_score:
            return []

        # Column edges: starts of tokens in the first rows, tolerance from
        # the median token width so ragged text still aligns.
        edges = np.concatenate([xs0, xs1])
        width_med = float(np.median(xs1 - xs0)) or 1.0
        col_groups = _cluster_1d(edges, max(3.0, cfg.cluster_gap_factor * width_med))
        if len(col_groups) < 2:
            return []
        x_bounds = _boundaries(col_groups, edges, x_lo, x_hi)

        # Row boundaries from vertical extents (groups may differ in height).
        y_bounds: list[float] = [y_lo]
        for a, b in zip(row_groups[:-1], row_groups[1:]):
            y_bounds.append((max(a) + min(b)) / 2)
        y_bounds.append(y_hi)

        cells: list[CellBox] = []
        n_cols = len(x_bounds) - 1
        for r in range(len(row_groups)):
            ry0, ry1 = y_bounds[r], y_bounds[r + 1]
            for t in tokens:
                cy = (t.bbox[1] + t.bbox[3]) / 2
                if not (ry0 <= cy < ry1):
                    continue
                c = self._span_col(t, x_bounds)
                cells.append(
                    CellBox(
                        row=r,
                        col=c,
                        bbox=(
                            max(x_bounds[c], t.bbox[0]),
                            t.bbox[1],
                            min(x_bounds[c + 1], t.bbox[2]),
                            t.bbox[3],
                        ),
                        col_span=self._span_count(t, x_bounds),
                    )
                )
        n_rows = len(row_groups)
        if len(cells) < cfg.min_cells:
            return []
        return [CellGrid(region=region, n_rows=n_rows, n_cols=n_cols, cells=cells)]

    @staticmethod
    def _span_col(token, x_bounds: list[float]) -> int:
        cx = (token.bbox[0] + token.bbox[2]) / 2
        for c in range(len(x_bounds) - 1):
            if x_bounds[c] <= cx < x_bounds[c + 1]:
                return c
        return len(x_bounds) - 2

    @staticmethod
    def _span_count(token, x_bounds: list[float]) -> int:
        """How many columns a wide token covers (merged cell detection)."""
        lo = np.searchsorted(x_bounds, token.bbox[0] + 1e-6, side="right") - 1
        hi = np.searchsorted(x_bounds, token.bbox[2] - 1e-6, side="right") - 1
        return max(1, int(hi - lo + 1))


__all__ = ["BorderlessClusterBackend"]
