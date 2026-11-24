"""CER mini-benchmark: OCR on raw vs preprocessed industrial HMI images.

Measures character error rate (engine.metrics.cer) with RapidOCR on synthetic
photographed-screen scenes (text panel warped onto a dark background) before
and after the preprocessing pipeline. Small sample, synthetic scenes: it is a
regression signal, not a claim about production accuracy.

Usage: uv run python benchmark/preprocess_cer.py
"""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

from engine.metrics import cer
from engine.preprocessing import PreprocessingPipeline

TEXTS = [
    "PUMP 04 STATUS OK",
    "TEMP 72.5 C PRESS 1013 hPa",
    "VALVE 12 OPEN ALARM NONE",
    "LINE 3 SPEED 240 m/min",
]
SCENES = ["clean", "skewed_3deg", "skewed_7deg", "perspective", "dark_glare"]


def make_panel(index: int) -> np.ndarray:
    img = Image.new("RGB", (900, 400), (250, 250, 250))
    draw = ImageDraw.Draw(img)
    for row, text in enumerate(TEXTS):
        draw.text((40, 40 + row * 80), TEXTS[(index + row) % len(TEXTS)], fill=(10, 10, 10))
    arr = np.asarray(img, dtype=np.uint8).copy()
    cv2.rectangle(arr, (6, 6), (893, 393), (0, 0, 0), 8)
    return arr


def make_scene(kind: str, index: int) -> np.ndarray:
    panel = make_panel(index)
    canvas = np.full((640, 900, 3), 45, dtype=np.uint8)
    size = (900, 640)
    if kind == "clean":
        # Paste the panel centred on the dark canvas.
        canvas = np.full((640, 900, 3), 45, dtype=np.uint8)
        y0, x0 = (640 - panel.shape[0]) // 2, (900 - panel.shape[1]) // 2
        canvas[y0 : y0 + panel.shape[0], x0 : x0 + panel.shape[1]] = panel
        return canvas
    elif kind in ("skewed_3deg", "skewed_7deg"):
        angle = 3.0 if kind == "skewed_3deg" else 7.0
        rotated, _ = cv2_rotation(panel, angle)
        # Scale/paste the rotated panel into the 640x900 canvas.
        scale = min(900 / rotated.shape[1], 640 / rotated.shape[0])
        resized = cv2.resize(rotated, None, fx=scale, fy=scale)
        y0 = (640 - resized.shape[0]) // 2
        x0 = (900 - resized.shape[1]) // 2
        canvas[y0 : y0 + resized.shape[0], x0 : x0 + resized.shape[1]] = resized
        return canvas
    elif kind == "perspective":
        src_quad = np.array([[60, 80], [840, 40], [870, 580], [30, 600]], dtype=np.float32)
        dst = np.array([[0, 0], [899, 0], [899, 639], [0, 639]], dtype=np.float32)
        forward = cv2.getPerspectiveTransform(src_quad, dst)
        scene_panel = cv2.warpPerspective(panel, forward, size)
        mask_src = cv2.warpPerspective(np.full(panel.shape[:2], 255, np.uint8), forward, size)
        return np.where(mask_src[:, :, None] > 0, scene_panel, canvas)
    else:  # dark_glare
        src_quad = np.array([[80, 70], [820, 50], [840, 560], [60, 580]], dtype=np.float32)
        dst = np.array([[0, 0], [899, 0], [899, 639], [0, 639]], dtype=np.float32)
        forward = cv2.getPerspectiveTransform(src_quad, dst)
        scene_panel = cv2.warpPerspective(panel, forward, size)
        mask_src = cv2.warpPerspective(np.full(panel.shape[:2], 255, np.uint8), forward, size)
        scene_panel = (scene_panel.astype(np.float32) * 0.75).astype(np.uint8)
        cv2.circle(scene_panel, (650, 120), 55, (255, 255, 255), -1)
        return np.where(mask_src[:, :, None] > 0, scene_panel, canvas)
    raise AssertionError(f"unknown scene kind: {kind}")


def cv2_rotation(image: np.ndarray, angle: float):
    height, width = image.shape[:2]
    center = (width / 2.0, height / 2.0)
    matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
    cos, sin = abs(matrix[0, 0]), abs(matrix[0, 1])
    new_size = (int(height * sin + width * cos), int(height * cos + width * sin))
    matrix[0, 2] += new_size[0] / 2.0 - center[0]
    matrix[1, 2] += new_size[1] / 2.0 - center[1]
    return (
        cv2.warpAffine(image, matrix, new_size, borderValue=(250, 250, 250)),
        matrix,
    )


def ocr_texts(image: np.ndarray) -> str:
    from rapidocr_onnxruntime import RapidOCR  # type: ignore[import-untyped]

    ocr = RapidOCR()
    result, _ = ocr(image)
    if not result:
        return ""
    return " ".join(item[1] for item in result)


def ground_truth(index: int) -> str:
    return " ".join(TEXTS[(index + row) % len(TEXTS)] for row in range(len(TEXTS)))


def main() -> None:
    pipeline = PreprocessingPipeline.for_profile("industrial_screen_photo")
    rows = []
    for kind in SCENES:
        for index in range(2):
            scene = make_scene(kind, index)
            truth = ground_truth(index)
            raw_text = ocr_texts(scene)
            raw_cer = cer(truth, raw_text)
            pre = pipeline.run(scene)
            pre_text = ocr_texts(np.ascontiguousarray(pre.image))
            pre_cer = cer(truth, pre_text)
            rows.append(
                {
                    "scene": kind,
                    "sample": index,
                    "cer_raw": round(raw_cer, 4),
                    "cer_preprocessed": round(pre_cer, 4),
                }
            )
            print(f"{kind:>12} #{index}: CER raw={raw_cer:.3f} preprocessed={pre_cer:.3f}")

    mean_raw = float(np.mean([r["cer_raw"] for r in rows]))
    mean_pre = float(np.mean([r["cer_preprocessed"] for r in rows]))
    summary = {"mean_cer_raw": round(mean_raw, 4), "mean_cer_preprocessed": round(mean_pre, 4)}
    print("\nSummary:", json.dumps(summary))

    out = Path("benchmark/results_preprocess_cer.json")
    out.write_text(json.dumps({"rows": rows, "summary": summary}, indent=2), encoding="utf-8")
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
