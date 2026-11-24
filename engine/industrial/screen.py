"""Screen normalization (P4 item 2).

Detects the monitor bezel / screen boundary, rectifies perspective with the
P1 preprocessing transforms, and reports moiré and glare as warnings. Built
exclusively on public P1 interfaces (``engine.preprocessing.transforms``).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from engine.preprocessing import transforms as tx


@dataclass
class ScreenReport:
    quad: np.ndarray | None  # detected screen corners in input coordinates
    rectified: np.ndarray  # perspective-corrected RGB image
    transform: np.ndarray | None  # 3x3 homography applied
    warnings: list[str] = field(default_factory=list)
    moire_score: float = 0.0
    glare_ratio: float = 0.0


def detect_screen_quad(image: np.ndarray) -> np.ndarray | None:
    """Screen boundary = the dominant bright, low-saturation quadrilateral."""
    import cv2

    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    _, bright = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    edges = cv2.Canny(blur, 50, 150).astype(np.uint8)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8)) | bright.astype(np.uint8)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    height, width = image.shape[:2]
    best, best_area = None, 0.05 * width * height
    for contour in contours:
        quad = cv2.approxPolyDP(contour, 0.02 * cv2.arcLength(contour, True), True)
        if len(quad) != 4:
            continue
        area = cv2.contourArea(quad)
        if area > best_area:
            best, best_area = quad, area
    if best is None:
        return None
    return tx.order_corners(best.reshape(-1, 2).astype(float))


def _moire_score(image: np.ndarray) -> float:
    """Relative energy of periodic interference peaks in the FFT spectrum."""
    gray = image.mean(axis=2) if image.ndim == 3 else image.astype(np.float32)
    gray = gray - gray.mean()
    spectrum = np.abs(np.fft.fftshift(np.fft.fft2(gray)))
    height, width = spectrum.shape
    center = (height // 2, width // 2)
    peak = spectrum.max()
    if peak <= 0:
        return 0.0
    # moiré shows as strong off-center periodic peaks in the upper quadrant band
    band = spectrum[
        max(0, center[0] - height // 8) : center[0],
        max(0, center[1] - width // 3) : center[1] + width // 3,
    ]
    if band.size == 0:
        return 0.0
    return float(band.max() / peak)


def normalize_screen(
    image: np.ndarray,
    *,
    force_rectify: bool = False,
) -> ScreenReport:
    """Detect the screen, rectify perspective and normalize the aspect ratio."""
    warnings: list[str] = []
    quad = detect_screen_quad(image)
    transform = None
    rectified = image
    if quad is not None:
        deviation = tx.quad_corner_deviation_deg(quad)
        if deviation > 1.0 or force_rectify:
            rectified, transform = _warp_to_quad(image, quad)
            if deviation > 3.0:
                warnings.append(f"perspective corrected: corner deviation {deviation:.1f} deg")
    else:
        warnings.append("screen boundary not detected; using full frame")

    glare = tx.detect_glare(rectified, tx.GlareConfig())
    if glare.glare_ratio > 0.02:
        warnings.append(f"glare on screen: {glare.glare_ratio:.1%} of pixels blown out")

    moire = _moire_score(rectified)
    if moire > 0.55:
        warnings.append(f"possible moiré interference (score {moire:.2f})")

    return ScreenReport(
        quad=quad,
        rectified=rectified,
        transform=transform,
        warnings=warnings,
        moire_score=moire,
        glare_ratio=glare.glare_ratio,
    )


def _warp_to_quad(image: np.ndarray, quad: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    import cv2

    width = int(round(max(np.linalg.norm(quad[i] - quad[(i + 1) % 4]) for i in range(4))))
    height = int(round(max(np.linalg.norm(quad[i] - quad[(i - 1) % 4]) for i in range(4))))
    width, height = max(1, width), max(1, height)
    dst = np.array(
        [[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]], dtype=np.float32
    )
    matrix = cv2.getPerspectiveTransform(quad.astype(np.float32), dst)
    warped = cv2.warpPerspective(image, matrix, (width, height))
    return warped, matrix
