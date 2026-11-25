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
    # Inversion-aware: on dark-background HMI screens the naive OTSU "bright"
    # mask locks onto the text, not the screen. Inverting the grayscale for
    # the brightness mask makes the dark screen interior the dominant blob
    # against a lighter bezel/room instead.
    frame_mean = float(gray.mean())
    work = 255 - gray if frame_mean < 127.0 else gray
    blur = cv2.GaussianBlur(work, (5, 5), 0)
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
        best = _border_line_quad(gray)
    if best is None:
        return None
    quad = tx.order_corners(best.reshape(-1, 2).astype(float))
    # Sanity check: the screen interior must differ in brightness from its
    # surroundings (a lit screen is brighter, a dark HMI screen darker than
    # the bezel/room around it). A quad hugging a flat area with no contrast
    # is not a screen boundary — fall back to the full frame.
    mask = np.zeros(gray.shape, np.uint8)
    pts = [np.asarray(quad, dtype=np.int32)]
    cv2.fillPoly(mask, pts, (255,))
    inside_mask = mask.astype(bool)
    inside = float(gray[inside_mask].mean()) if inside_mask.any() else 0.0
    outside = float(gray[~inside_mask].mean()) if (~inside_mask).any() else inside
    if abs(inside - outside) < 15.0:
        return None
    return quad


def _border_line_quad(gray: np.ndarray) -> np.ndarray | None:
    """Fallback screen quad from dominant border lines (Hough).

    Used when the contour search fails because glare or a low-contrast
    bezel boundary breaks the screen outline into arcs: strong straight
    lines near each image border still mark the screen edges. Falls back
    to a gradient-profile scan (strongest horizontal/vertical edge per
    border region) when Hough misses a side — bezel edges are often
    black-on-black and too weak for line detection. Returns a 4x2 array
    in order_corners order, or None when a border cannot be located.
    """
    import cv2

    height, width = gray.shape[:2]
    edges = cv2.Canny(cv2.GaussianBlur(gray, (5, 5), 0), 50, 150)
    lines = cv2.HoughLinesP(
        edges, 1, np.pi / 720, threshold=100,
        minLineLength=int(min(width, height) * 0.5), maxLineGap=40,
    )
    best: dict[str, tuple[float, float]] = {}  # region -> (strength, pos)
    if lines is not None:
        for x1, y1, x2, y2 in lines.reshape(-1, 4):
            angle = np.degrees(np.arctan2(y2 - y1, x2 - x1)) % 180.0
            length = float(np.hypot(x2 - x1, y2 - y1))
            if min(angle, 180.0 - angle) < 10.0:  # horizontal
                pos = (y1 + y2) / 2.0
                region = "top" if pos < height / 2.0 else "bottom"
            elif angle > 80.0:  # vertical
                pos = (x1 + x2) / 2.0
                region = "left" if pos < width / 2.0 else "right"
            else:
                continue
            if region not in best or length > best[region][0]:
                best[region] = (length, pos)
    if set(best) != {"top", "bottom", "left", "right"}:
        gradient_best = _border_gradient_quad(gray)
        if gradient_best is not None:
            best = gradient_best
    if set(best) != {"top", "bottom", "left", "right"}:
        return None
    top, bottom = best["top"][1], best["bottom"][1]
    left, right = best["left"][1], best["right"][1]
    return tx.order_corners(
        np.array(
            [[left, top], [right, top], [right, bottom], [left, bottom]], dtype=np.float64
        )
    )


def _border_gradient_quad(gray: np.ndarray) -> dict[str, tuple[float, float]] | None:
    """Strongest gradient line per border region (outer 18% of the frame).

    Screens photographed front-on have a bezel edge too soft for Hough but
    still the strongest row/column gradient near each border.
    """
    import cv2

    height, width = gray.shape[:2]
    g = cv2.GaussianBlur(gray.astype(np.float32), (5, 5), 0)
    col = np.abs(cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)).mean(axis=0)
    row = np.abs(cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)).mean(axis=1)
    # Exclude the frame edge itself: the image border is always a hard
    # gradient step but is not the screen boundary.
    inner = 4
    margin_v, margin_h = int(height * 0.18), int(width * 0.18)

    def peak(profile: np.ndarray, lo: int, hi: int) -> tuple[float, float] | None:
        lo, hi = max(lo, inner), min(hi, len(profile) - inner)
        if hi <= lo:
            return None
        idx = int(np.argmax(profile[lo:hi])) + lo
        strength = float(profile[idx])
        if strength < 8.0:  # noise floor: no real edge in this region
            return None
        return strength, float(idx)

    found: dict[str, tuple[float, float]] = {}
    for name, res in (
        ("left", peak(col, 0, margin_v)),
        ("right", peak(col, width - margin_v, width)),
        ("top", peak(row, 0, margin_h)),
        ("bottom", peak(row, height - margin_h, height)),
    ):
        if res is None:
            return None
        found[name] = res
    return found


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
