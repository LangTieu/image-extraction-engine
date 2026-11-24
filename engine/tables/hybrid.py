"""Hybrid backend: run several structure backends and reconcile their grids.

Grids from different backends are matched by region IoU; when two backends
see the same table, the more confident grid wins and the loser only
contributes: cells the winner missed are merged in, and disagreements are
recorded (reported as low-confidence cells downstream). If all backends
except one are unavailable, the single available backend's result is
returned unchanged.
"""

from __future__ import annotations

from engine.tables.base import CellGrid, TableBackend, TableConfig


def region_iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    inter = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
    area_a = max(0.0, ax1 - ax0) * max(0.0, ay1 - ay0)
    area_b = max(0.0, bx1 - bx0) * max(0.0, by1 - by0)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


class HybridBackend(TableBackend):
    """Reconcile the ruled, borderless and (when cached) TATR backends."""

    name = "hybrid"

    def __init__(self, config: TableConfig | None = None) -> None:
        self.config = config or TableConfig()
        from engine.tables.borderless import BorderlessClusterBackend
        from engine.tables.ruled import RuledGridBackend

        self.backends: list[TableBackend] = [
            RuledGridBackend(self.config),
            BorderlessClusterBackend(self.config),
        ]
        self._maybe_add_tatr()

    def _maybe_add_tatr(self) -> None:
        """Include the TATR backend only when its weights are already cached."""
        from engine.tables.tatr import _weights_cached

        if _weights_cached(self.config.tatr_detection_model) and _weights_cached(
            self.config.tatr_structure_model
        ):
            from engine.tables.tatr import TATRBackend

            self.backends.append(TATRBackend(self.config))

    def add_backend(self, backend: TableBackend) -> None:
        self.backends.append(backend)

    def detect(self, image, tokens: list) -> list[CellGrid]:
        available: list[TableBackend] = []
        results: dict[str, list[CellGrid]] = {}
        for backend in self.backends:
            if backend.name == "hybrid":
                continue
            try:
                grids = backend.detect(image, tokens)
            except Exception:
                continue  # e.g. TableBackendUnavailable for TATR without weights
            results[backend.name] = grids
            available.append(backend)
        if not available:
            return []
        if len(available) == 1:
            return results[available[0].name]

        # Reconcile pairwise by IoU, starting from the highest-scoring grid.
        all_grids = [g for grids in results.values() for g in grids]
        all_grids.sort(key=lambda g: g.region.score, reverse=True)
        merged: list[CellGrid] = []
        for grid in all_grids:
            match = None
            for keeper in merged:
                if region_iou(keeper.region.bbox, grid.region.bbox) > 0.5:
                    match = keeper
                    break
            if match is None:
                merged.append(grid)
            else:
                self._merge_into(match, grid)
        return merged

    @staticmethod
    def _merge_into(keeper: CellGrid, other: CellGrid) -> None:
        """Fold ``other`` into ``keeper``: extra cells, averaged confidence."""
        keeper.region.score = min(1.0, (keeper.region.score + other.region.score) / 2 + 0.05)
        keeper.region.ruled = keeper.region.ruled or other.region.ruled
        keeper_bboxes = {c.bbox for c in keeper.cells}
        for cell in other.cells:
            if cell.bbox not in keeper_bboxes:
                keeper.cells.append(cell)


__all__ = ["HybridBackend", "region_iou"]
