"""P3 benchmark: table structure & content accuracy on the seed datasets.

Usage: .venv/bin/python -m benchmark.tables_eval [--out results_tables.json]

For every table-category seed sample (table_image = dense small-font,
coil_table = coil tables) each backend (ruled / borderless / hybrid) runs
OCR (P2 pipeline) + table extraction. Scores against ground truth:

- detection recall: a GT table is "detected" when an extracted table's bbox
  IoU with it exceeds 0.5;
- structure accuracy: cell-adjacency F1 (from P0 convention): pairs of cells
  that are horizontal/vertical neighbours in GT vs extraction;
- content accuracy: exact-match rate of cell texts over matched rows/cols;
- latency per table.

Results are written to benchmark/results_tables.json and printed as a
table per category. --viz additionally writes debug overlays under
benchmark/viz_tables/.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
from PIL import Image

from engine.ocr import GeneralOCR, PaddleOCREngine
from engine.ocr.base import OCRToken
from engine.preprocessing.pipeline import PreprocessingPipeline
from engine.schema import ExtractionResult, Table
from engine.tables import TableConfig, TablePipeline
from engine.tables.hybrid import region_iou
from engine.tables.viz import render_debug

CATEGORIES = ("table_image", "coil_table")
IOU_MATCH = 0.5


def _gt_tables(gt: ExtractionResult) -> list[Table]:
    return [t for t in gt.tables if t.bbox is not None]


def _adjacency_pairs(table: Table) -> set[tuple[int, int, int, int]]:
    """(row_a, col_a, row_b, col_b) neighbour pairs among filled cells."""
    by_pos = {(c.row_index, c.col_index): c for c in table.cells if c.text not in (None, "")}
    pairs: set[tuple[int, int, int, int]] = set()
    for r, c in by_pos:
        if (r, c + 1) in by_pos:
            pairs.add((r, c, r, c + 1))
        if (r + 1, c) in by_pos:
            pairs.add((r, c, r + 1, c))
    return pairs


def _content_pairs(table: Table) -> set[tuple[int, int, str]]:
    return {
        (c.row_index, c.col_index, (c.text or "").strip())
        for c in table.cells
        if c.text not in (None, "")
    }


def score_tables(gt_tables: list[Table], got_tables: list[Table]) -> dict:
    detected = 0
    adj_f1s: list[float] = []
    content_scores: list[float] = []
    for gt in gt_tables:
        if gt.bbox is None:
            continue
        gtb = (gt.bbox.x0, gt.bbox.y0, gt.bbox.x1, gt.bbox.y1)
        match = None
        for got in got_tables:
            if got.bbox is None:
                continue
            gb = (got.bbox.x0, got.bbox.y0, got.bbox.x1, got.bbox.y1)
            if region_iou(gtb, gb) > IOU_MATCH:
                match = got
                break
        if match is None:
            adj_f1s.append(0.0)
            content_scores.append(0.0)
            continue
        detected += 1
        gt_adj, got_adj = _adjacency_pairs(gt), _adjacency_pairs(match)
        if gt_adj or got_adj:
            tp = len(gt_adj & got_adj)
            precision = tp / len(got_adj) if got_adj else 0.0
            recall = tp / len(gt_adj) if gt_adj else 0.0
            f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        else:
            f1 = 1.0
        adj_f1s.append(f1)
        gt_c, got_c = _content_pairs(gt), _content_pairs(match)
        tp = len(gt_c & got_c)
        content_scores.append(2 * tp / (len(gt_c) + len(got_c)) if gt_c or got_c else 1.0)
    return {
        "gt_tables": len(gt_tables),
        "detected": detected,
        "detection_recall": detected / len(gt_tables) if gt_tables else 1.0,
        "structure_adj_f1": float(np.mean(adj_f1s)) if adj_f1s else 1.0,
        "content_accuracy": float(np.mean(content_scores)) if content_scores else 1.0,
    }


def _load_tokens(ocr: GeneralOCR, image_path: Path):
    """Preprocess (P1) then OCR (P2); returns processed image, tokens, log."""
    img = _open_png(image_path)
    pre = PreprocessingPipeline.for_profile("screenshot").run(img)
    doc = ocr.recognize_image(pre.image, transform_log=pre.transform_log)
    tokens = [OCRToken(text=t.text, bbox=t.bbox, confidence=t.confidence) for t in doc.tokens]
    return pre.image, tokens


def _open_png(image_path: Path) -> np.ndarray:
    from PIL import ImageFile

    ImageFile.LOAD_TRUNCATED_IMAGES = True
    return np.asarray(Image.open(image_path).convert("RGB")).copy()


def _render_gt_tables(gt: ExtractionResult) -> np.ndarray:
    """Render the GT tables as ruled synthetic scenes (seed PNGs are
    truncated fixtures — same convention as ocr_cer/preprocess_cer)."""
    from PIL import Image, ImageDraw

    width = 1200
    rows_total = sum(max(1, len(t.rows) + (1 if t.columns else 0)) for t in gt.tables)
    height = 80 + rows_total * 46
    img = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    y = 40
    for t in gt.tables:
        cols = t.columns or []
        data = t.rows or []
        n_rows = (1 if cols else 0) + len(data)
        n_cols = max(1, len(cols) or max((len(r) for r in data), default=1))
        cell_w = (width - 160) // n_cols
        cell_h = 44
        for r in range(n_rows + 1):
            draw.rectangle(
                [80, y + r * cell_h, 80 + n_cols * cell_w, y + r * cell_h + 2], fill=(0, 0, 0)
            )
        for c in range(n_cols + 1):
            draw.rectangle(
                [80 + c * cell_w, y, 82 + c * cell_w, y + n_rows * cell_h], fill=(0, 0, 0)
            )
        grid = ([cols] if cols else []) + [list(r) for r in data]
        for r, row in enumerate(grid):
            for c, text in enumerate(row):
                if text:
                    draw.text((92 + c * cell_w, y + r * cell_h + 12), str(text), fill=(10, 10, 10))
        y += n_rows * cell_h + 40
    return np.asarray(img, dtype=np.uint8).copy()


def run(ocr: GeneralOCR, out: Path | None, viz_dir: Path | None) -> dict:
    results: dict = {}
    for category in CATEGORIES:
        base = Path("benchmark/seed") / category
        per_backend: dict[str, dict] = {
            name: {"recall": [], "structure": [], "content": [], "latency_ms": []}
            for name in ("ruled", "borderless", "tatr", "hybrid")
        }
        for gt_path in sorted((base / "ground_truth").glob("*.json")):
            image_path = base / "images" / gt_path.stem
            if not image_path.exists():
                continue
            gt = ExtractionResult.model_validate(json.loads(gt_path.read_text("utf-8")))
            gts = _gt_tables(gt)
            image = _render_gt_tables(gt)
            pre = PreprocessingPipeline.for_profile("screenshot").run(image)
            doc = ocr.recognize_image(pre.image, transform_log=pre.transform_log)
            tokens = [
                OCRToken(text=tok.text, bbox=tok.bbox, confidence=tok.confidence)
                for tok in doc.tokens
            ]
            for name in per_backend:
                start = time.perf_counter()
                pipeline = TablePipeline(TableConfig(backend=name))
                result = pipeline.extract(image, tokens, table_name=category)
                elapsed = (time.perf_counter() - start) * 1000.0
                scores = score_tables(gts, result.tables)
                per_backend[name]["recall"].append(scores["detection_recall"])
                per_backend[name]["structure"].append(scores["structure_adj_f1"])
                per_backend[name]["content"].append(scores["content_accuracy"])
                per_backend[name]["latency_ms"].append(elapsed / max(1, len(result.tables)))
                if viz_dir is not None and name == "hybrid":
                    viz_dir.mkdir(parents=True, exist_ok=True)
                    grids = pipeline.backend.detect(image, tokens)
                    from PIL import Image as PILImage

                    canvas = render_debug(image, grids, tokens=tokens)
                    PILImage.fromarray(canvas[:, :, ::-1]).save(
                        viz_dir / f"{gt_path.stem}_{name}.png"
                    )
        results[category] = {
            name: {
                "detection_recall": float(np.mean(v["recall"])) if v["recall"] else 0.0,
                "structure_adj_f1": float(np.mean(v["structure"])) if v["structure"] else 0.0,
                "content_accuracy": float(np.mean(v["content"])) if v["content"] else 0.0,
                "latency_ms_per_table": float(np.mean(v["latency_ms"])) if v["latency_ms"] else 0.0,
                "n_samples": len(v["recall"]),
            }
            for name, v in per_backend.items()
        }
    if out is not None:
        out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="benchmark/results_tables.json")
    parser.add_argument("--viz", action="store_true")
    args = parser.parse_args()
    ocr = GeneralOCR([PaddleOCREngine()])
    viz_dir = Path("benchmark/viz_tables") if args.viz else None
    results = run(ocr, Path(args.out), viz_dir)
    for category, per_backend in results.items():
        print(f"\n== {category} ==")
        for name, scores in per_backend.items():
            print(
                f"  {name:11s} recall={scores['detection_recall']:.2f} "
                f"structure={scores['structure_adj_f1']:.2f} "
                f"content={scores['content_accuracy']:.2f} "
                f"latency={scores['latency_ms_per_table']:.0f}ms/table "
                f"(n={scores['n_samples']})"
            )


if __name__ == "__main__":
    main()
