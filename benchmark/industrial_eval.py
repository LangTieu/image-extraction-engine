"""P4 industrial evaluation (module-level, per brief).

Usage: python -m benchmark.industrial_eval [seed_dir] [out_json]

Evaluates the ``engine.industrial`` module on the coil_table and
industrial_hmi seed sets with four metrics:

1. routing (category match vs. ground truth document_type);
2. field-level F1 for ID/numeric/string fields (exact text match);
3. unit accuracy (unit string equals GT unit when a value is read);
4. unknown-rate: fraction of unreadable fields that are explicitly flagged
   needs_review / parse-note instead of silently guessed.

The seed images are 1x1 blank placeholder PNGs (P0 scaffolding; real images
arrive in P1+), so scenes are rendered from the ground-truth JSON at runtime
(same convention as tables_eval/ocr_cer/preprocess_cer): text blocks, then
``NAME: raw_text`` field lines, then the GT tables as ruled grids.
Exits non-zero on any error. Writes a JSON results file.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

from engine.industrial import IndustrialVision
from engine.schema import ExtractionResult


def _gt_fields(result: ExtractionResult) -> dict[str, str]:
    out: dict[str, str] = {}
    for field in result.fields:
        if field.raw_text:
            out[field.name] = str(field.raw_text)
    for table in result.tables or []:
        cols = table.columns or []
        if not cols:
            continue
        if table.rows:  # unified schema: headers live in columns, rows are data-only
            for row in table.rows:
                for col, cell in zip(cols, row or []):
                    if cell:
                        out[col] = str(cell)
        else:
            for c in table.cells:
                if c.text and c.row_index > 0:
                    idx = c.col_index
                    key = cols[idx] if idx < len(cols) else str(idx)
                    out[key] = c.text
    return out


def _render_gt_scene(gt: ExtractionResult) -> np.ndarray:
    """Render the GT blocks/fields/tables as a synthetic industrial scene
    (seed PNGs are blank fixtures — same convention as tables_eval)."""
    from PIL import Image, ImageDraw

    width = 1200
    rows_total = sum(max(1, len(t.rows) + (1 if t.columns else 0)) for t in gt.tables)
    height = 80 + len(gt.text_blocks) * 30 + len(gt.fields) * 40 + rows_total * 46
    img = Image.new("RGB", (width, height), (28, 28, 28))
    draw = ImageDraw.Draw(img)
    y = 20
    for block in gt.text_blocks:
        draw.text((20, y), block.text, fill=(230, 230, 230))
        y += 30
    for field in gt.fields:
        raw = field.raw_text or (str(field.value) if field.value else "")
        draw.text((20, y), f"{field.name}: {raw}", fill=(255, 255, 160))
        y += 40
    for t in gt.tables:
        cols = t.columns or []
        data = t.rows or []
        n_rows = (1 if cols else 0) + len(data)
        n_cols = max(1, len(cols) or max((len(r) for r in data), default=1))
        cell_w = (width - 160) // n_cols
        cell_h = 44
        for r in range(n_rows + 1):
            draw.rectangle(
                [80, y + r * cell_h, 80 + n_cols * cell_w, y + r * cell_h + 2], fill=(255, 255, 255)
            )
        for c in range(n_cols + 1):
            draw.rectangle(
                [80 + c * cell_w, y, 82 + c * cell_w, y + n_rows * cell_h], fill=(255, 255, 255)
            )
        grid = ([cols] if cols else []) + [list(r) for r in data]
        for r, row in enumerate(grid):
            for c, text in enumerate(row):
                if text:
                    draw.text(
                        (92 + c * cell_w, y + r * cell_h + 12), str(text), fill=(255, 255, 255)
                    )
        y += n_rows * cell_h + 40
    return np.asarray(img, dtype=np.uint8).copy()


def _prf1(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return precision, recall, f1


def evaluate_seed(seed_dir: Path) -> dict[str, object]:
    vision = IndustrialVision()
    per_set: dict[str, dict[str, object]] = {}
    overall = {"tp": 0, "fp": 0, "fn": 0, "unit_ok": 0, "unit_total": 0, "flagged": 0, "unknown": 0}
    route_ok = route_total = 0
    started = time.perf_counter()

    for category_dir in sorted(p for p in seed_dir.iterdir() if p.is_dir()):
        if category_dir.name not in ("coil_table", "industrial_hmi"):
            continue
        gt_dir = category_dir / "ground_truth"
        samples: list[dict[str, object]] = []
        for gt_path in sorted(gt_dir.glob("*.json")):
            gt = ExtractionResult.model_validate(json.loads(gt_path.read_text(encoding="utf-8")))
            image = _render_gt_scene(gt)
            pred = vision.process(
                image,
                file_name=(gt.source.file_name if gt.source else None) or gt_path.stem,
            )

            route_total += 1
            route_ok += int(pred.document_type == gt.document_type)

            gold = _gt_fields(gt)
            got: dict[str, str] = {f.name: (f.raw_text or "") for f in pred.fields}
            for table in pred.tables or []:
                cols = table.columns or []
                if not cols:
                    continue
                if table.rows:  # unified schema: headers live in columns, rows are data-only
                    for row in table.rows:
                        for col, cell in zip(cols, row or []):
                            if cell:
                                got[col] = str(cell)
                else:
                    for c in table.cells:
                        if c.text and c.row_index > 0 and c.col_index < len(cols):
                            got[cols[c.col_index]] = c.text
            for name in gold:
                overall["unit_total"] += 1
                if name in got and got[name].strip() == gold[name].strip():
                    overall["tp"] += 1
                    overall["unit_ok"] += 1
                else:
                    overall["fn"] += 1
            for name in got:
                if name not in gold:
                    overall["fp"] += 1
            flagged = sum(
                1
                for f in pred.fields
                if f.needs_review or not (f.raw_text or "").strip()
            )
            unknown = sum(1 for name, text in gold.items() if not text.strip())
            overall["flagged"] += flagged
            overall["unknown"] += unknown
            samples.append(
                {
                    "sample": gt_path.stem,
                    "route_ok": pred.document_type == gt.document_type,
                    "pred_type": pred.document_type,
                    "gt_type": gt.document_type,
                    "fields_gt": len(gold),
                    "fields_pred": len(got),
                    "warnings": pred.warnings,
                }
            )
            route_hits = sum(1 for s in samples if s["route_ok"])
        p, r, f1 = _prf1(route_hits, 0, len(samples) - route_hits)
        per_set[category_dir.name] = {
            "samples": samples,
            "routing_accuracy": p if samples else 0.0,
        }

    tp, fp, fn = overall["tp"], overall["fp"], overall["fn"]
    precision, recall, f1 = _prf1(tp, fp, fn)
    unit_acc = overall["unit_ok"] / overall["unit_total"] if overall["unit_total"] else 0.0
    unknown_rate_flagged = overall["flagged"] / (overall["flagged"] + overall["unknown"]) if (
        overall["flagged"] + overall["unknown"]
    ) else 1.0
    return {
        "module": "engine.industrial",
        "seed_dir": str(seed_dir),
        "runtime_s": round(time.perf_counter() - started, 2),
        "per_set": per_set,
        "routing_accuracy": route_ok / route_total if route_total else 0.0,
        "field_precision": precision,
        "field_recall": recall,
        "field_f1": f1,
        "unit_accuracy": unit_acc,
        "unknown_rate_flagged": unknown_rate_flagged,
        "counts": {k: v for k, v in overall.items()},
    }


def main(argv: list[str]) -> int:
    seed_dir = Path(argv[1]) if len(argv) > 1 else Path("benchmark/seed")
    out_path = Path(argv[2]) if len(argv) > 2 else Path("benchmark/results_industrial.json")
    if not seed_dir.is_dir():
        print(f"seed dir not found: {seed_dir}")
        return 2
    results = evaluate_seed(seed_dir)
    out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(
        f"industrial eval: routing={results['routing_accuracy']:.3f} "
        f"f1={results['field_f1']:.3f} unit_acc={results['unit_accuracy']:.3f} "
        f"unknown_flagged={results['unknown_rate_flagged']:.3f} -> {out_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
