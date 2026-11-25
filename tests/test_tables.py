"""P3 tests: table backends, token assignment, pipeline merge and guards.

No network, no model downloads: the ruled tests render a table scene with
PIL, the borderless/cell tests use synthetic OCR tokens and the TATR test
stubs the HF cache probe. See ``mlai_p3_test_brief.md``.
"""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from engine.ocr.base import OCRToken
from engine.preprocessing.mapping import TransformLog
from engine.schema import Table
from engine.tables.base import (
    CellBox,
    CellGrid,
    TableBackend,
    TableBackendUnavailable,
    TableConfig,
    TableRegion,
)
from engine.tables.borderless import BorderlessClusterBackend
from engine.tables.cells import assign_tokens, grid_to_table, normalize_column_key
from engine.tables.hybrid import HybridBackend, region_iou
from engine.tables.pipeline import TablePipeline, merge_pages
from engine.tables.ruled import RuledGridBackend
from engine.tables.tatr import TATRBackend

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _font(size: int = 16):
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size)
    except OSError:
        return ImageFont.load_default()


def _token(text: str, bbox: tuple[float, float, float, float], conf: float = 0.95) -> OCRToken:
    return OCRToken(text=text, bbox=bbox, confidence=conf)


def _grid_image(n_cols: int = 3, n_rows: int = 3) -> tuple[np.ndarray, list[float], list[float]]:
    """Render a ruled table (black lines on white) plus its line positions."""
    x0, y0, x1, y1 = 40.0, 40.0, 440.0, 320.0
    xs = np.linspace(x0, x1, n_cols + 1)
    ys = np.linspace(y0, y1, n_rows + 1)
    img = Image.new("RGB", (480, 360), "white")
    draw = ImageDraw.Draw(img)
    for x in xs:
        draw.line([(x, y0), (x, y1)], fill="black", width=2)
    for y in ys:
        draw.line([(x0, y), (x1, y)], fill="black", width=2)
    return np.asarray(img), list(xs), list(ys)


def _ruled_scene() -> tuple[np.ndarray, list[OCRToken], list[list[str]]]:
    """Ruled 3x3 coil table: header row + two data rows of known values."""
    table = [
        ["COIL_NO", "GRADE", "WEIGHT"],
        ["12345", "AISI304", "12.5"],
        ["67890", "AISI316", "18.25"],
    ]
    image, xs, ys = _grid_image()
    pil = Image.fromarray(image)
    draw = ImageDraw.Draw(pil)
    font = _font()
    tokens: list[OCRToken] = []
    for r, row in enumerate(table):
        for c, text in enumerate(row):
            cx, cy = (xs[c] + xs[c + 1]) / 2, (ys[r] + ys[r + 1]) / 2
            draw.text((cx, cy), text, fill="black", font=font, anchor="mm")
            bb = draw.textbbox((cx, cy), text, font=font, anchor="mm")
            tokens.append(_token(text, tuple(bb)))  # type: ignore[arg-type]
    return np.asarray(pil), tokens, table


# ---------------------------------------------------------------------------
# Ruled backend
# ---------------------------------------------------------------------------


def test_ruled_backend_detects_grid_and_columns():
    image, tokens, _ = _ruled_scene()
    grids = RuledGridBackend(TableConfig()).detect(image, tokens)
    assert len(grids) == 1
    grid = grids[0]
    assert grid.n_rows == 3
    assert grid.n_cols == 3
    assert len(grid.cells) == 9
    assert grid.region.ruled is True
    # Cells cover the ruled extent and stay inside the image.
    assert grid.region.bbox[0] < 60 and grid.region.bbox[2] > 420


# ---------------------------------------------------------------------------
# Borderless backend
# ---------------------------------------------------------------------------


def _borderless_tokens() -> list[OCRToken]:
    """2 rows x 3 columns of aligned tokens, no ruling lines.

    Within a column the two rows' tokens are offset by 30px so their edges
    cluster into one group per column; the 40px gap between columns splits
    there, giving exactly 3 column bounds.
    """
    tokens = []
    for r, cy in enumerate((20.0, 60.0)):
        for c in range(3):
            x0 = 10.0 + 130.0 * c + (0.0 if r == 0 else 30.0)
            tokens.append(_token(f"t{r}{c}", (x0, cy - 8, x0 + 60.0, cy + 8)))
    return tokens


def test_borderless_clusters_tokens_into_rows_and_columns():
    tokens = _borderless_tokens()
    grids = BorderlessClusterBackend(TableConfig()).detect(np.zeros((100, 320), np.uint8), tokens)
    assert len(grids) == 1
    grid = grids[0]
    assert grid.n_rows == 2
    assert grid.n_cols == 3
    assert grid.region.ruled is False
    for cell in grid.cells:
        token = tokens[cell.row * 3 + cell.col]
        assert (cell.bbox[0], cell.bbox[1], cell.bbox[2], cell.bbox[3]) == token.bbox


def test_borderless_needs_at_least_four_tokens():
    few = _borderless_tokens()[:3]
    assert BorderlessClusterBackend(TableConfig()).detect(np.zeros((100, 320), np.uint8), few) == []


# ---------------------------------------------------------------------------
# Hybrid reconciliation
# ---------------------------------------------------------------------------


def test_region_iou():
    assert region_iou((0, 0, 10, 10), (0, 0, 10, 10)) == pytest.approx(1.0)
    assert region_iou((0, 0, 10, 10), (20, 20, 30, 30)) == 0.0
    assert region_iou((0, 0, 10, 10), (5, 0, 15, 10)) == pytest.approx(5 * 10 / (100 + 100 - 50))


class _FakeBackend(TableBackend):
    def __init__(self, name: str, grids: list[CellGrid] | Exception):
        self.name = name  # instance attribute: TableBackend.name is a plain attr
        self._grids = grids

    def detect(self, image, tokens: list) -> list[CellGrid]:
        if isinstance(self._grids, Exception):
            raise self._grids
        return self._grids


def _grid(backend: str, score: float, cells: list[tuple[float, float, float, float]]) -> CellGrid:
    return CellGrid(
        region=TableRegion(bbox=(10, 10, 200, 200), score=score, backend=backend),
        n_rows=1,
        n_cols=len(cells),
        cells=[CellBox(row=0, col=i, bbox=bb) for i, bb in enumerate(cells)],
    )


def test_hybrid_keeps_higher_scored_grid_and_folds_extra_cells():
    hybrid = HybridBackend(TableConfig())
    hybrid.backends = []  # ignore the real ruled/borderless backends
    hybrid.add_backend(
        _FakeBackend("high", [_grid("high", 0.9, [(10, 10, 70, 60), (70, 10, 140, 60)])])
    )
    hybrid.add_backend(
        _FakeBackend(
            "low",
            [_grid("low", 0.7, [(10, 10, 70, 60), (70, 10, 140, 60), (140, 10, 200, 60)])],
        )
    )
    grids = hybrid.detect(np.zeros((220, 220), np.uint8), [])
    assert len(grids) == 1
    keeper = grids[0]
    assert keeper.region.backend == "high"  # higher-scored grid wins
    assert len(keeper.cells) == 3  # the third cell was folded in
    assert keeper.region.ruled is False
    assert keeper.region.score == pytest.approx(0.85)  # mean confidence, +0.05 bump


def test_hybrid_skips_unavailable_backend_and_keeps_single_result():
    hybrid = HybridBackend(TableConfig())
    hybrid.backends = []  # ignore the real ruled/borderless backends
    winner = _grid("solo", 0.8, [(10, 10, 70, 60)])
    hybrid.add_backend(_FakeBackend("broken", TableBackendUnavailable("no weights")))
    hybrid.add_backend(_FakeBackend("solo", [winner]))
    assert hybrid.detect(np.zeros((220, 220), np.uint8), []) == [winner]


# ---------------------------------------------------------------------------
# Token -> cell assignment and grid_to_table
# ---------------------------------------------------------------------------


def _manual_grid(header_span: bool = False) -> CellGrid:
    cells = [
        CellBox(row=0, col=0, bbox=(0, 0, 100, 40)),
        CellBox(row=0, col=1, bbox=(100, 0, 200, 40)),
        CellBox(row=1, col=0, bbox=(0, 40, 100, 80)),
        CellBox(row=1, col=1, bbox=(100, 40, 200, 80)),
    ]
    return CellGrid(
        region=TableRegion(bbox=(0, 0, 200, 80), score=0.9, backend="test"),
        n_rows=2,
        n_cols=2,
        cells=cells,
    )


def test_straddling_token_goes_to_cell_it_mostly_covers():
    cells = [_manual_grid().cells[i] for i in range(2)]
    straddler = _token("A", (60, 5, 130, 35))  # 40px in cell0, 30px in cell1
    assignment = assign_tokens(cells, [straddler])
    assert list(assignment) == [0]


def test_multiline_cell_tokens_join_sorted_by_x():
    grid = _manual_grid()
    tokens = [_token("123", (60, 45, 95, 75)), _token("coil", (5, 45, 55, 75))]
    table = grid_to_table(grid, tokens)
    assert table.rows[0][0] == "coil 123"
    conf = next(c for c in table.cells if (c.row_index, c.col_index) == (1, 0)).confidence
    assert conf is not None and conf == pytest.approx(0.95)


def test_header_detection_and_column_n_fallback():
    grid = _manual_grid()
    tokens = [_token("HOT_COIL", (5, 5, 95, 35)), _token("v", (5, 45, 45, 75))]
    table = grid_to_table(grid, tokens)
    assert table.columns == ["HOT_COIL", "column_1"]  # empty header -> column_N
    assert table.rows == [["v", None]]
    # Empty body cell stays explicitly None, with the cell present and textless.
    empty = next(c for c in table.cells if (c.row_index, c.col_index) == (1, 1))
    assert empty.text is None and empty.bbox is not None


def test_no_header_keeps_raw_rows_and_pipeline_warns():
    grid = _manual_grid()
    grid.has_header = False
    tokens = [_token("a", (5, 45, 45, 75)), _token("b", (105, 45, 145, 75))]
    table = grid_to_table(grid, tokens)
    assert table.columns == [] and table.rows == [[None, None], ["a", "b"]]


@pytest.mark.parametrize(
    ("name", "key"),
    [
        ("Hot Coil No.", "HOT_COIL_NO"),
        ("Grade/Spec", "GRADE_SPEC"),
        ("  weight  (t) ", "WEIGHT_T"),
    ],
)
def test_normalize_column_key(name: str, key: str):
    assert normalize_column_key(name) == key


# ---------------------------------------------------------------------------
# Pipeline: extract, coordinate mapping, warnings
# ---------------------------------------------------------------------------


def test_extract_maps_bbox_through_transform_log():
    tokens = _borderless_tokens()
    pipeline = TablePipeline(TableConfig(backend="borderless"))
    log = TransformLog()
    log.add("resize", np.array([[2.0, 0, 0], [0, 2.0, 0], [0, 0, 1.0]]), scale=2.0)
    result = pipeline.extract(np.zeros((100, 320), np.uint8), tokens, transform_log=log)
    assert result.status == "completed" and result.backends_used == ["borderless"]
    table = result.tables[0]
    assert table.bbox is not None
    # The region bbox is token coordinates scaled 2x back to original pixels.
    assert table.bbox.x0 == pytest.approx(min(t.bbox[0] for t in tokens) * 2, abs=1.0)
    assert table.bbox.y1 == pytest.approx(max(t.bbox[3] for t in tokens) * 2, abs=1.0)
    assert all(c.bbox is not None for c in table.cells)
    # Provenance: original-space box recorded before mapping, per node.
    assert table.prov and table.prov[0].coord_space == "original"
    assert table.prov[0].unit == "px"
    assert table.prov[0].bbox.x0 == pytest.approx(min(t.bbox[0] for t in tokens) * 2, abs=1.0)
    for cell in table.cells:
        assert cell.prov, "every cell carries prov"
        assert cell.prov[0].bbox == cell.bbox
        assert cell.prov[0].coord_space == "original" and cell.prov[0].unit == "px"


def test_extract_warns_when_no_header_row():
    pipeline = TablePipeline(TableConfig(backend="borderless"))
    empty_header = _manual_grid()
    empty_header.has_header = False
    pipeline.backend = _FakeBackend("borderless", [empty_header])  # inject no-header grid
    result = pipeline.extract(np.zeros((220, 220), np.uint8), [])
    assert result.status == "completed_with_warnings"
    assert result.warnings and "no header row" in result.warnings[0]


# ---------------------------------------------------------------------------
# merge_pages
# ---------------------------------------------------------------------------


def _result(*tables: Table):
    from engine.tables.pipeline import TableResult

    return TableResult(tables=list(tables))


def test_merge_pages_appends_continuation_and_renames_duplicates():
    t1 = Table(table_name="coil", columns=["A", "B"], rows=[["1", "2"]])
    t_cont = Table(table_name="coil", columns=["A", "B"], rows=[["3", "4"]])
    t_other = Table(table_name="coil", columns=["X"], rows=[["9"]])
    merged = merge_pages([_result(t1), _result(t_cont), _result(t_other)])
    assert len(merged) == 2
    assert merged[0].rows == [["1", "2"], ["3", "4"]]  # continuation appended
    assert merged[1].table_name == "coil_p2"  # duplicate name renamed, not overwritten


# ---------------------------------------------------------------------------
# TATR guard: never downloads
# ---------------------------------------------------------------------------


def test_tatr_raises_unavailable_without_cached_weights(monkeypatch):
    calls: list[dict] = []
    try:
        import huggingface_hub
    except ImportError:
        huggingface_hub = None
    if huggingface_hub is not None:

        def _no_download(repo_id, **kwargs):
            calls.append({"repo_id": repo_id, **kwargs})
            raise RuntimeError("network access disabled in tests")

        monkeypatch.setattr(huggingface_hub, "snapshot_download", _no_download)
    backend = TATRBackend(TableConfig())
    with pytest.raises(TableBackendUnavailable, match="BLOCKED.md"):
        backend.detect(np.zeros((100, 100), np.uint8), [])
    # If the probe ran at all, it stayed local-only: it never downloads.
    assert all(call.get("local_files_only") is True for call in calls)


class _FakeModel:
    def __call__(self, **kwargs):
        return None


class _FakeInputs(dict):
    def to(self, *args, **kwargs):  # processor chain calls .to(device)
        return self


class _FakeProcessor:
    """Stands in for AutoImageProcessor: fixed detections, no model run."""

    def __init__(self, results):
        self._results = results

    def __call__(self, images=None, return_tensors="pt"):
        return _FakeInputs()

    def post_process_object_detection(self, outputs, threshold, target_sizes):
        return self._results


def test_tatr_cell_offset_covers_every_cell_including_last_row():
    import torch

    backend = TATRBackend(TableConfig())
    det = _FakeProcessor(
        [
            {
                "scores": torch.tensor([0.99]),
                "labels": torch.tensor([0]),
                "boxes": torch.tensor([[10.0, 20.0, 110.0, 120.0]]),
            }
        ]
    )
    # Two row bands and two column bands in crop space.
    struct = _FakeProcessor(
        [
            {
                "scores": torch.tensor([0.9] * 4),
                "labels": torch.tensor([0, 0, 1, 1]),
                "boxes": torch.tensor(
                    [
                        [0.0, 0.0, 80.0, 25.0],  # row 0: y 0..25
                        [0.0, 25.0, 80.0, 50.0],  # row 1: y 25..50
                        [0.0, 0.0, 30.0, 50.0],  # col 0: x 0..30
                        [30.0, 0.0, 60.0, 50.0],  # col 1: x 30..60
                    ]
                ),
            }
        ]
    )
    backend._loaded = True
    backend._det = _FakeModel()
    backend._det_processor = det
    backend._struct = _FakeModel()
    backend._struct_processor = struct
    backend._id2label_det = {0: "table"}
    backend._id2label_struct = {0: "table row", 1: "table column"}

    grids = backend.detect(np.zeros((200, 200, 3), np.uint8), [])
    assert len(grids) == 1
    grid = grids[0]
    assert grid.n_rows == 2 and grid.n_cols == 1
    assert [(c.row, c.col) for c in grid.cells] == [(0, 0), (1, 0)]  # last row emitted
    # Crop-space bands offset by the region bbox (10, 20): every cell.
    assert grid.cells[0].bbox == pytest.approx((10.0, 20.0, 40.0, 45.0))
    assert grid.cells[1].bbox == pytest.approx((10.0, 45.0, 40.0, 70.0))


# ---------------------------------------------------------------------------
# Coil-table regression: no silent column shifts
# ---------------------------------------------------------------------------


def test_coil_table_columns_do_not_shift():
    image, tokens, table = _ruled_scene()
    result = TablePipeline(TableConfig(backend="ruled")).extract(image, tokens, table_name="coil")
    assert result.backends_used == ["ruled"]
    assert len(result.tables) == 1
    got = result.tables[0]
    assert [normalize_column_key(c) for c in got.columns] == table[0]
    assert got.rows == [table[1], table[2]]
    # Every value sits in the column its header names.
    for row in got.rows:
        assert row[0].isdigit() and row[1].startswith("AISI") and float(row[2]) > 0
