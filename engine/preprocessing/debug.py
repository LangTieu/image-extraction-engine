"""Debug visualization: before/after side-by-side PNG plus quad overlay."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from engine.preprocessing.pipeline import PreprocessedImage


def render_quad_overlay(image: np.ndarray, quad: np.ndarray | None) -> np.ndarray:
    out = image.copy()
    if quad is not None:
        points = np.asarray(quad, dtype=np.int32).reshape(-1, 1, 2)
        cv2.polylines(out, [points], isClosed=True, color=(220, 30, 30), thickness=3)
    return out


def save_debug_comparison(
    result: PreprocessedImage, original: np.ndarray, path: str | Path
) -> Path:
    """Write side-by-side (original with quad overlay, preprocessed) PNG."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    left = render_quad_overlay(np.asarray(original), result.perspective_quad_original)
    right = np.asarray(result.image)
    height = max(left.shape[0], right.shape[0])
    width = left.shape[1] + right.shape[1] + 12
    canvas = np.full((height, width, 3), 255, dtype=np.uint8)
    canvas[: left.shape[0], : left.shape[1]] = left
    canvas[: right.shape[0], -right.shape[1] :] = right
    Image.fromarray(canvas).save(target, format="PNG")
    return target
