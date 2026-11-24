"""Table extraction primitives (P3).

A :class:`TableBackend` turns one grayscale/RGB image plus the OCR tokens
found on it into a list of :class:`CellGrid`: one grid per detected table
region, in the *same pixel coordinates as the input image*. The orchestrator
(:mod:`engine.tables.pipeline`) assigns tokens to cells, maps coordinates
back to the original image and fills the unified-schema ``Table`` model.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

TABLE_BACKENDS = ("ruled", "borderless", "hybrid", "tatr")


class TableBackendUnavailable(RuntimeError):
    """Raised when a backend needs weights that are not in the local cache.

    Backends must never download models at runtime (P3 guard): the Table
    Transformer backend probes the HF cache with ``local_files_only=True``
    and raises this when the weights are absent.
    """


@dataclass
class TableRegion:
    """One detected table region in image pixel coordinates."""

    bbox: tuple[float, float, float, float]  # x0, y0, x1, y1
    score: float  # detection confidence in [0, 1]
    backend: str = ""
    ruled: bool = False  # True if the region shows ruling lines


@dataclass
class CellBox:
    """One grid cell: row/col indices plus its pixel bbox.

    ``row_span``/``col_span`` > 1 mark merged cells; the bbox then covers
    the merged area.
    """

    row: int
    col: int
    bbox: tuple[float, float, float, float]
    row_span: int = 1
    col_span: int = 1


@dataclass
class CellGrid:
    """A detected table region with its cell grid (no text yet)."""

    region: TableRegion
    n_rows: int
    n_cols: int
    cells: list[CellBox] = field(default_factory=list)
    has_header: bool = True  # grid distinguishes a header row


@dataclass
class TableConfig:
    """Configuration for the table extraction stage."""

    backend: str = "hybrid"  # one of TABLE_BACKENDS
    min_region_score: float = 0.3
    min_cells: int = 4  # fewer cells than this is not a table
    ruled_line_scale: int = 30  # morphological kernel = 1/scale of extent
    cluster_gap_factor: float = 0.6  # borderless: gap > factor * median gap splits
    tatr_detection_model: str = "microsoft/table-transformer-detection"
    tatr_structure_model: str = "microsoft/table-transformer-structure-recognition"


class TableBackend(ABC):
    """Abstract table structure backend."""

    name: str = "table"

    @abstractmethod
    def detect(self, image: object, tokens: list) -> list[CellGrid]:
        """Return cell grids for every table found in ``image``.

        ``tokens`` are :class:`engine.ocr.base.OCRToken` in the same
        coordinates as the image; borderless and hybrid backends use them.
        """
