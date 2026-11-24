"""P2 OCR benchmark: CER/WER of the GeneralOCR path on seed ground truth.

Seed PNGs are truncated fixtures, so — like benchmark/preprocess_cer.py —
this benchmark renders the seed ground-truth text blocks into synthetic
scenes and measures engine.metrics.cer/wer of the OCR output against the
ground truth. Small synthetic sample: a regression signal, not a production
accuracy claim.

Usage:
    python -m benchmark.ocr_cer [--engine paddle|tesseract] [--set photo_document]

Writes JSON results to benchmark/results_ocr_cer.json and prints a summary.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from engine.metrics import cer as character_error_rate
from engine.metrics import wer as word_error_rate
from engine.ocr import GeneralOCR, PaddleOCREngine, TesseractEngine

SEED_ROOT = Path(__file__).parent / "seed"
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def _render_gt(gt_json: dict, width: int = 1000) -> np.ndarray:
    blocks = gt_json.get("text_blocks") or []
    lines = [b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("text")]
    font = ImageFont.truetype(FONT_PATH, 30)
    height = max(120, 40 + len(lines) * 44)
    img = Image.new("RGB", (width, height), (250, 250, 250))
    draw = ImageDraw.Draw(img)
    for row, text in enumerate(lines):
        draw.text((30, 20 + row * 44), text, fill=(10, 10, 10), font=font)
    return np.asarray(img, dtype=np.uint8).copy()


def _ground_truth_text(gt_json: dict) -> str:
    blocks = gt_json.get("text_blocks") or gt_json.get("lines") or []
    return "\n".join(
        block.get("text", "") if isinstance(block, dict) else str(block) for block in blocks
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", choices=["paddle", "tesseract"], default="tesseract")
    parser.add_argument("--set", dest="dataset", default=None, help="limit to one seed set")
    args = parser.parse_args()

    engine = PaddleOCREngine() if args.engine == "paddle" else TesseractEngine()
    ocr = GeneralOCR([engine])
    sets = [args.dataset] if args.dataset else [d.name for d in SEED_ROOT.iterdir() if d.is_dir()]
    results = []
    for name in sorted(sets):
        gt_dir = SEED_ROOT / name / "ground_truth"
        if not gt_dir.is_dir():
            continue
        for gt_path in sorted(gt_dir.glob("*.json")):
            gt_json = json.loads(gt_path.read_text())
            gt_text = _ground_truth_text(gt_json)
            if not gt_text.strip():
                continue
            image = _render_gt(gt_json)
            t0 = time.perf_counter()
            doc = ocr.recognize_image(image)
            hyp = doc.text()
            results.append(
                {
                    "set": name,
                    "source": gt_path.stem,
                    "cer": character_error_rate(gt_text, hyp),
                    "wer": word_error_rate(gt_text, hyp),
                    "chars": len(gt_text),
                    "elapsed_ms": (time.perf_counter() - t0) * 1000,
                    "engine": args.engine,
                }
            )
    out_path = Path(__file__).parent / "results_ocr_cer.json"
    out_path.write_text(json.dumps(results, indent=2))
    if results:
        for name in sorted({r["set"] for r in results}):
            rows = [r for r in results if r["set"] == name]
            cer = sum(r["cer"] * r["chars"] for r in rows) / max(1, sum(r["chars"] for r in rows))
            wer = sum(r["wer"] for r in rows) / len(rows)
            print(f"{name}: CER={cer:.3f} WER={wer:.3f} n={len(rows)}")
    else:
        print("no seed samples matched")
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
