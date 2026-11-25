"""P8 robustness perturbations: image-space degradations at severity 1-3.

Each perturbation returns a new uint8 RGB array; severities are cumulative
strength steps, not incremental applications (a severity-3 image is the
severity-1 transform applied harder, not twice).
"""

from __future__ import annotations

import io
from collections.abc import Callable

import numpy as np
from PIL import Image, ImageFilter

_RESAMPLE_BILINEAR = Image.Resampling.BILINEAR
_AFFINE = Image.Transform.AFFINE


def _pil(image: np.ndarray) -> Image.Image:
    return Image.fromarray(image.astype(np.uint8), mode="RGB")


def brightness(image: np.ndarray, severity: int) -> np.ndarray:
    factor = [1.0, 0.55, 1.6, 0.35][severity]
    return np.clip(np.asarray(_pil(image), dtype=np.float32) * factor, 0, 255).astype(np.uint8)


def gaussian_blur(image: np.ndarray, severity: int) -> np.ndarray:
    radius = [0.0, 1.0, 2.0, 4.0][severity]
    return np.asarray(_pil(image).filter(ImageFilter.GaussianBlur(radius)), dtype=np.uint8)


def gaussian_noise(image: np.ndarray, severity: int) -> np.ndarray:
    sigma = [0.0, 8.0, 18.0, 35.0][severity]
    rng = np.random.default_rng(7)
    noise = rng.normal(0.0, sigma, image.shape)
    return np.clip(image.astype(np.float32) + noise, 0, 255).astype(np.uint8)


def jpeg_compression(image: np.ndarray, severity: int) -> np.ndarray:
    quality = [100, 60, 35, 15][severity]
    buf = io.BytesIO()
    _pil(image).save(buf, format="JPEG", quality=quality)
    buf.seek(0)
    return np.asarray(Image.open(buf).convert("RGB"), dtype=np.uint8)


def scale_down(image: np.ndarray, severity: int) -> np.ndarray:
    factor = [1.0, 0.6, 0.4, 0.25][severity]
    w = max(32, int(image.shape[1] * factor))
    h = max(32, int(image.shape[0] * factor))
    small = _pil(image).resize((w, h), _RESAMPLE_BILINEAR)
    resized = small.resize((image.shape[1], image.shape[0]), _RESAMPLE_BILINEAR)
    return np.asarray(resized, dtype=np.uint8)


def perspective_shear(image: np.ndarray, severity: int) -> np.ndarray:
    shift = [0.0, 0.05, 0.12, 0.2][severity]
    w, h = image.shape[1], image.shape[0]
    coeffs = (1, shift, -shift * h, shift, 1, 0, 0, 0)
    out = _pil(image).transform((w, h), _AFFINE, coeffs, resample=_RESAMPLE_BILINEAR)
    return np.asarray(out, dtype=np.uint8)


PERTURBATIONS: dict[str, Callable[[np.ndarray, int], np.ndarray]] = {
    "brightness": brightness,
    "blur": gaussian_blur,
    "noise": gaussian_noise,
    "jpeg": jpeg_compression,
    "scale_down": scale_down,
    "shear": perspective_shear,
}

MAX_SEVERITY = 3
BREAKDOWN_DROP = 0.10  # relative primary-metric drop that counts as breakdown


def breakdown_severity(scores: list[float], clean: float) -> int | None:
    """First severity where the score drops more than BREAKDOWN_DROP relative
    to the clean score; None when the curve never breaks."""
    if clean <= 0:
        return None
    for idx, value in enumerate(scores, start=1):
        if value < clean * (1.0 - BREAKDOWN_DROP):
            return idx
    return None
