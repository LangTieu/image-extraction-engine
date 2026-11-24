"""Table Transformer backend (P3 optional).

Wraps ``microsoft/table-transformer-detection`` and
``microsoft/table-transformer-structure-recognition``. Weights are probed
with ``local_files_only=True`` — this backend **never downloads** (P3
guard: stop below 2 GiB free, see BLOCKED.md). Without cached weights it
raises :class:`TableBackendUnavailable` and the pipeline falls back to the
OpenCV+OCR backends.
"""

from __future__ import annotations

import numpy as np

from engine.tables.base import (
    CellBox,
    CellGrid,
    TableBackend,
    TableBackendUnavailable,
    TableConfig,
    TableRegion,
)

_DEVICE = "cpu"


def _weights_cached(model_id: str) -> bool:
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        return False
    try:
        snapshot_download(repo_id=model_id, local_files_only=True)
        return True
    except Exception:
        return False


class TATRBackend(TableBackend):
    """Table Transformer detection + structure recognition (weights optional)."""

    name = "tatr"

    def __init__(self, config: TableConfig | None = None) -> None:
        self.config = config or TableConfig()
        self._loaded = False
        self._det = None
        self._struct = None
        self._id2label_det: dict[int, str] = {}
        self._id2label_struct: dict[int, str] = {}

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        cfg = self.config
        if not (
            _weights_cached(cfg.tatr_detection_model) and _weights_cached(cfg.tatr_structure_model)
        ):
            raise TableBackendUnavailable(
                "Table Transformer weights not in the local HF cache and "
                "runtime downloads are disabled (see BLOCKED.md)"
            )
        from transformers import AutoImageProcessor, AutoModelForObjectDetection

        det_proc = AutoImageProcessor.from_pretrained(
            cfg.tatr_detection_model, local_files_only=True
        )
        det_model = AutoModelForObjectDetection.from_pretrained(
            cfg.tatr_detection_model, local_files_only=True
        )
        struct_proc = AutoImageProcessor.from_pretrained(
            cfg.tatr_structure_model, local_files_only=True
        )
        struct_model = AutoModelForObjectDetection.from_pretrained(
            cfg.tatr_structure_model, local_files_only=True
        )
        self._det = det_model.to(_DEVICE).eval()
        self._struct = struct_model.to(_DEVICE).eval()
        self._det_processor, self._struct_processor = det_proc, struct_proc
        self._id2label_det = det_model.config.id2label
        self._id2label_struct = struct_model.config.id2label
        self._loaded = True

    def detect(self, image, tokens: list) -> list[CellGrid]:
        self._ensure_loaded()
        assert self._det is not None and self._det_processor is not None
        assert self._struct is not None and self._struct_processor is not None
        import torch

        rgb = image if image.ndim == 3 else np.stack([image] * 3, axis=-1)
        with torch.no_grad():
            inputs = self._det_processor(images=rgb, return_tensors="pt").to(_DEVICE)
            outputs = self._det(**inputs)
            target_sizes = torch.tensor([rgb.shape[:2]])
            results = self._det_processor.post_process_object_detection(
                outputs, threshold=self.config.min_region_score, target_sizes=target_sizes
            )[0]

        grids: list[CellGrid] = []
        h, w = rgb.shape[:2]
        for score, label, box in zip(
            results["scores"].tolist(), results["labels"].tolist(), results["boxes"].tolist()
        ):
            if self._id2label_det[label].lower() != "table":
                continue
            x0, y0, x1, y1 = box
            region = TableRegion(
                bbox=(x0, y0, x1, y1), score=float(score), backend=self.name, ruled=False
            )
            crop = rgb[max(0, int(y0)) : min(h, int(y1)), max(0, int(x0)) : min(w, int(x1))]
            grid = self._structure(crop, region, tokens)
            if grid is not None:
                grids.append(grid)
        return grids

    def _structure(self, crop: np.ndarray, region: TableRegion, tokens: list) -> CellGrid | None:
        assert self._struct is not None and self._struct_processor is not None
        import torch

        with torch.no_grad():
            inputs = self._struct_processor(images=crop, return_tensors="pt").to(_DEVICE)
            outputs = self._struct(**inputs)
            target_sizes = torch.tensor([crop.shape[:2]])
            res = self._struct_processor.post_process_object_detection(
                outputs, threshold=0.5, target_sizes=target_sizes
            )[0]
        rows: list[tuple[float, float]] = []
        cols: list[tuple[float, float]] = []
        spans: list[tuple[float, float, float, float]] = []
        for label, box in zip(res["labels"].tolist(), res["boxes"].tolist()):
            name = self._id2label_struct[label].lower()
            if name.startswith("table row"):
                rows.append((box[1], box[3]))
            elif name.startswith("table column"):
                cols.append((box[0], box[2]))
            elif name.startswith("table spanning cell"):
                spans.append(box)
        rows.sort()
        cols.sort()
        if len(rows) < 2 or len(cols) < 2:
            return None
        cells = [
            CellBox(row=r, col=c, bbox=(cols[c][0], rows[r][0], cols[c][1], rows[r][1]))
            for r in range(len(rows) - 1)
            for c in range(len(cols) - 1)
        ]
        for box in spans:  # merged cells: mark the covered grid cells' extent
            self._mark_span(box, rows, cols, cells)
        return CellGrid(region=region, n_rows=len(rows) - 1, n_cols=len(cols) - 1, cells=cells)

    @staticmethod
    def _mark_span(box, rows, cols, cells: list[CellBox]) -> None:
        r0 = max(i for i, (a, _) in enumerate(rows) if a <= box[1])
        r1 = max(i for i, (_, b) in enumerate(rows) if b >= box[3])
        c0 = max(i for i, (a, _) in enumerate(cols) if a <= box[0])
        c1 = max(i for i, (_, b) in enumerate(cols) if b >= box[2])
        for cell in cells:
            if r0 <= cell.row < r1 and c0 <= cell.col < c1:
                cell.row_span = r1 - r0
                cell.col_span = c1 - c0


__all__ = ["TATRBackend"]
