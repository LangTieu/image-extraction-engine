"""P8 harness core: deterministic split, scene rendering, pipeline variants, metrics.

The seed PNGs are blank fixtures, so scenes are rendered from the ground-truth
JSON at runtime (same convention as ocr_cer / industrial_eval / tables_eval).

Everything the P8 run writes into an artifact is derived from inputs that are
recorded in config.json: split seed, split definition, variant list, git SHA.
"""

from __future__ import annotations

import hashlib
import platform
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from engine.industrial.pipeline import IndustrialVision
from engine.metrics import coil_id_accuracy, field_accuracy, table_structure_accuracy
from engine.ocr import GeneralOCR, PaddleOCREngine, TesseractEngine
from engine.preprocessing.pipeline import PreprocessingPipeline
from engine.schema import ExtractionResult

SEED_ROOT = Path(__file__).parent / "seed"
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

COIL_ID_FIELDS = ("HOT_COIL_NO", "COLD_COIL_NO", "COIL_ID")
INDUSTRIAL_CATEGORIES = ("coil_table", "industrial_hmi")

VARIANTS: dict[str, dict[str, object]] = {
    "default_tesseract": {"ocr_kind": "tesseract", "preprocess": True},
    "ocr_paddle": {"ocr_kind": "paddle", "preprocess": True},
    "ocr_ensemble": {"ocr_kind": "ensemble", "preprocess": True},
    "no_preprocess": {"ocr_kind": "tesseract", "preprocess": False},
}


# --------------------------------------------------------------------------
# split


def split_seed(
    split_seed: int = 42,
    dev_frac: float = 0.4,
    categories: list[str] | None = None,
) -> dict[str, list[dict[str, str]]]:
    """Deterministic dev/test split of the seed samples.

    A sample belongs to dev when sha1(f"{split_seed}:{relpath}") % 100 is
    below dev_frac * 100. Both fractions and the seed land in the artifact.
    """
    wanted = set(categories or ())
    out: dict[str, list[dict[str, str]]] = {"dev": [], "test": []}
    for category_dir in sorted(p for p in SEED_ROOT.iterdir() if p.is_dir()):
        if wanted and category_dir.name not in wanted:
            continue
        gt_dir = category_dir / "ground_truth"
        if not gt_dir.is_dir():
            continue
        for gt_path in sorted(gt_dir.glob("*.json")):
            rel = f"{category_dir.name}/{gt_path.name}"
            digest = hashlib.sha1(f"{split_seed}:{rel}".encode()).hexdigest()
            bucket = "dev" if int(digest[:8], 16) % 100 < round(dev_frac * 100) else "test"
            out[bucket].append({"category": category_dir.name, "gt": str(gt_path)})
    return out


# --------------------------------------------------------------------------
# ground truth


def load_gt(gt_path: str | Path) -> ExtractionResult:
    import json

    return ExtractionResult.model_validate(
        json.loads(Path(gt_path).read_text(encoding="utf-8"))
    )


def gt_text(gt: ExtractionResult) -> str:
    blocks = gt.text_blocks or []
    lines = [b.text for b in blocks if b.text]
    for f in gt.fields:
        raw = f.raw_text or (str(f.value) if f.value is not None else "")
        if raw:
            lines.append(f"{f.name}: {raw}")
    for t in gt.tables:
        cols = t.columns or []
        if cols:
            lines.append(" ".join(cols))
        for row in t.rows or []:
            lines.append(" ".join(str(c) for c in row if c))
    return "\n".join(lines)


def gt_field_map(gt: ExtractionResult) -> dict[str, str]:
    out: dict[str, str] = {}
    for f in gt.fields:
        raw = f.raw_text or (str(f.value) if f.value is not None else "")
        out[f.name] = raw
    for t in gt.tables:
        cols = t.columns or []
        if not cols:
            continue
        if t.rows:
            for row in t.rows or []:
                for col, cell in zip(cols, row or []):
                    if cell:
                        out[col] = str(cell)
        else:
            for c in t.cells:
                if c.text and c.row_index > 0 and c.col_index < len(cols):
                    out[cols[c.col_index]] = c.text
    return out


def gt_cells(gt: ExtractionResult) -> list[tuple[int, int]]:
    cells: list[tuple[int, int]] = []
    for t in gt.tables:
        for c in t.cells:
            if c.text not in (None, ""):
                cells.append((c.row_index, c.col_index))
    return cells


# --------------------------------------------------------------------------
# scene rendering


def render_scene(gt: ExtractionResult) -> np.ndarray:
    """Render the GT blocks/fields/tables as a synthetic scene image."""
    width = 1200
    rows_total = sum(max(1, len(t.rows) + (1 if t.columns else 0)) for t in gt.tables)
    height = max(
        120,
        80 + len(gt.text_blocks) * 30 + len(gt.fields) * 40 + rows_total * 46,
    )
    dark = gt.document_type in INDUSTRIAL_CATEGORIES
    bg = (28, 28, 28) if dark else (250, 250, 250)
    fg = (230, 230, 230) if dark else (10, 10, 10)
    field_fg = (255, 255, 160) if dark else (20, 20, 120)
    img = Image.new("RGB", (width, int(height)), bg)
    draw = ImageDraw.Draw(img)
    y = 20
    for block in gt.text_blocks:
        draw.text((20, y), block.text, fill=fg)
        y += 30
    for f in gt.fields:
        raw = f.raw_text or (str(f.value) if f.value is not None else "")
        draw.text((20, y), f"{f.name}: {raw}", fill=field_fg)
        y += 40
    for t in gt.tables:
        cols = t.columns or []
        data = [list(r) for r in (t.rows or [])]
        n_rows = (1 if cols else 0) + len(data)
        n_cols = max(1, len(cols) or max((len(r) for r in data), default=1))
        cell_w = (width - 160) // n_cols
        cell_h = 44
        line = (255, 255, 255) if dark else (60, 60, 60)
        for r in range(n_rows + 1):
            draw.rectangle(
                [80, y + r * cell_h, 80 + n_cols * cell_w, y + r * cell_h + 2], fill=line
            )
        for c in range(n_cols + 1):
            draw.rectangle([80 + c * cell_w, y, 82 + c * cell_w, y + n_rows * cell_h], fill=line)
        grid = ([cols] if cols else []) + data
        for r, row in enumerate(grid):
            for c, text in enumerate(row):
                if text:
                    draw.text((92 + c * cell_w, y + r * cell_h + 12), str(text), fill=fg)
        y += n_rows * cell_h + 40
    return np.asarray(img, dtype=np.uint8).copy()


# --------------------------------------------------------------------------
# pipeline variants


def build_ocr(kind: str) -> GeneralOCR:
    if kind == "paddle":
        return GeneralOCR([PaddleOCREngine()])
    if kind == "ensemble":
        return GeneralOCR([PaddleOCREngine(), TesseractEngine()])
    return GeneralOCR([TesseractEngine()])


@dataclass
class PipelineVariant:
    name: str
    ocr_kind: str = "tesseract"
    preprocess: bool = True

    def build(self) -> PipelineVariantRunner:
        preprocessing = (
            PreprocessingPipeline.for_profile("screenshot")
            if self.preprocess
            else PreprocessingPipeline.from_dict("none", {})
        )
        vision = IndustrialVision(
            preprocessing=preprocessing,
            ocr=build_ocr(self.ocr_kind),
        )
        return PipelineVariantRunner(self, vision)


@dataclass
class PipelineVariantRunner:
    variant: PipelineVariant
    vision: IndustrialVision

    def process(self, image: np.ndarray, file_name: str) -> tuple[ExtractionResult, float]:
        t0 = time.perf_counter()
        result = self.vision.process(image, file_name=file_name)
        return result, (time.perf_counter() - t0) * 1000.0


# --------------------------------------------------------------------------
# per-sample metrics


def _norm_text(text: str) -> str:
    return " ".join(text.split()).strip().lower()


def _values_equal(ref: str, got: str) -> bool:
    if _norm_text(ref) == _norm_text(got):
        return True
    try:
        return abs(float(str(got).replace(",", ".")) - float(str(ref).replace(",", "."))) <= 1e-6
    except (TypeError, ValueError):
        return False


def predict_field_map(result: ExtractionResult) -> dict[str, str]:
    out: dict[str, str] = {}
    for f in result.fields:
        out[f.name] = f.raw_text or (str(f.value) if f.value is not None else "")
    for t in result.tables:
        cols = t.columns or []
        if not cols:
            continue
        if t.rows:
            for row in t.rows or []:
                for col, cell in zip(cols, row or []):
                    if cell:
                        out[col] = str(cell)
        else:
            for c in t.cells:
                if c.text and c.row_index > 0 and c.col_index < len(cols):
                    out[cols[c.col_index]] = c.text
    return out


def score_sample(
    gt: ExtractionResult,
    pred: ExtractionResult,
    elapsed_ms: float,
) -> dict[str, object]:
    gold = gt_field_map(gt)
    got = predict_field_map(pred)
    got_str: dict[str, str] = {k: str(v) for k, v in got.items()}
    gold_vals: dict[str, str | float | int] = dict(gold)
    field_hits = {k: _values_equal(v, got[k]) for k, v in gold.items() if k in got}
    missing = [k for k in gold if k not in got]
    extra = [k for k in got if k not in gold]
    wrong = [k for k, ok in field_hits.items() if not ok]

    confidences = [f.confidence for f in pred.fields if f.confidence is not None]
    correctness = [
        _values_equal(gold[f.name], f.raw_text or "")
        for f in pred.fields
        if f.name in gold and f.raw_text is not None
    ]
    wrong_flagged = [
        f.name
        for f in pred.fields
        if f.name in gold
        and f.raw_text is not None
        and not _values_equal(gold[f.name], f.raw_text)
        and f.needs_review
    ]

    ref_cells = gt_cells(gt)
    pred_cells = [
        (c.row_index, c.col_index)
        for t in pred.tables
        for c in t.cells
        if c.text not in (None, "")
    ]
    structure = table_structure_accuracy(ref_cells, pred_cells)

    return {
        "gt_type": gt.document_type,
        "pred_type": pred.document_type,
        "route_ok": gt.document_type == pred.document_type,
        "elapsed_ms": elapsed_ms,
        "gt_text_chars": len(gt_text(gt)),
        "fields_gold": gold,
        "fields_pred": got,
        "field_hits": len(field_hits) - len(wrong),
        "field_missing": missing,
        "field_wrong": wrong,
        "wrong_flagged": wrong_flagged,
        "field_extra": extra,
        "field_accuracy": field_accuracy(gold_vals, {k: got_str.get(k, "") for k in gold}),
        "coil_id_accuracy": coil_id_accuracy(
            {k: str(v) for k, v in gold.items() if k in COIL_ID_FIELDS},
            got_str,
        ),
        "table_cells_ref": len(ref_cells),
        "table_structure_f1": structure.adjacency.f1 if ref_cells else None,
        "confidence": float(np.mean(confidences)) if confidences else None,
        "field_confidences": confidences,
        "field_correctness": correctness,
        "flagged": sum(1 for f in pred.fields if f.needs_review),
        "status": pred.extraction_status.value,
        "warnings": list(pred.warnings),
    }


def aggregate_text_cer_wer(
    samples: list[dict[str, object]],
    cer_wer: list[tuple[float, float]],
) -> dict[str, float]:
    """Corpus-level CER (char-weighted) and mean WER from OCR stage scores."""
    chars = sum(int(str(s["gt_text_chars"])) for s in samples) or 1
    cer = sum(c * int(str(s["gt_text_chars"])) for (c, _w), s in zip(cer_wer, samples)) / chars
    wer = float(np.mean([w for _c, w in cer_wer])) if cer_wer else 0.0
    return {"cer": float(cer), "wer": wer}


# --------------------------------------------------------------------------
# environment


def environment_info() -> dict[str, object]:
    import engine

    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "processors": __import__("os").cpu_count(),
        "engine_version": getattr(engine, "__version__", "0.0.1"),
    }


def bootstrap_ci(
    values: list[float],
    *,
    statistic: str = "mean",
    n_boot: int = 1000,
    seed: int = 42,
    alpha: float = 0.05,
) -> dict[str, float]:
    """Percentile bootstrap CI for the mean (or median) of per-sample values."""
    if not values:
        return {"low": 0.0, "high": 0.0, "point": 0.0}
    rng = np.random.default_rng(seed)
    arr = np.asarray(values, dtype=float)
    pick = np.mean if statistic == "mean" else np.median
    stats = [float(pick(rng.choice(arr, size=len(arr), replace=True))) for _ in range(n_boot)]
    return {
        "low": float(np.quantile(stats, alpha / 2)),
        "high": float(np.quantile(stats, 1 - alpha / 2)),
        "point": float(pick(arr)),
    }


def expected_calibration_error(
    confidences: list[float], correct: list[bool], n_bins: int = 10
) -> dict[str, object]:
    """ECE with equal-width bins; also returns the reliability curve."""
    if not confidences:
        return {"ece": 0.0, "bins": []}
    conf = np.asarray(confidences)
    corr = np.asarray(correct, dtype=float)
    bins: list[dict[str, float]] = []
    ece = 0.0
    for i in range(n_bins):
        lo, hi = i / n_bins, (i + 1) / n_bins
        mask = (conf > lo) & (conf <= hi) if i else (conf >= lo) & (conf <= hi)
        if not mask.any():
            continue
        acc = float(corr[mask].mean())
        avg_conf = float(conf[mask].mean())
        weight = int(mask.sum()) / len(conf)
        ece += weight * abs(acc - avg_conf)
        bins.append(
            {
                "low": lo,
                "high": hi,
                "count": int(mask.sum()),
                "accuracy": acc,
                "confidence": avg_conf,
            }
        )
    return {"ece": float(ece), "bins": bins}


@dataclass
class SampleRecord:
    category: str
    sample: str
    gt_path: str
    scores: dict[str, object] = field(default_factory=dict)
    cer: float = 0.0
    wer: float = 0.0
