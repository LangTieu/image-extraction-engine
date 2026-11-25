"""Preprocessing transforms: pure functions array-in / (array, matrix)-out.

Each transform takes an RGB uint8 array plus its config dataclass and returns
the transformed array. Geometry-changing transforms also return the 3x3
homography that maps post-transform coordinates back to pre-transform
coordinates, for the TransformLog.

Out of scope here: OCR, table detection and classification.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from engine.preprocessing.mapping import IDENTITY


def _homography_from_affine(matrix_2x3: np.ndarray) -> np.ndarray:
    full = np.eye(3, dtype=np.float64)
    full[:2, :] = matrix_2x3
    return full


def _inverse_affine(matrix_2x3: np.ndarray) -> np.ndarray:
    """Inverse of a 2x3 affine, as a 3x3 homography (post -> pre coordinates)."""
    return np.linalg.inv(_homography_from_affine(matrix_2x3))


@dataclass
class RotateConfig:
    """Explicit rotation in degrees (counter-clockwise). None = no-op."""

    angle: float | None = None


@dataclass
class OrientationConfig:
    """Detect 0/90/180/270 rotation from text-line projections; fix small skew.

    detect = enable the 90-degree orientation classifier.
    deskew = enable fine skew correction (Hough lines on text edges).
    """

    detect: bool = True
    deskew: bool = True
    max_skew_deg: float = 15.0
    max_correction_angle: float = 10.0


@dataclass
class PerspectiveConfig:
    """Detect the largest quadrilateral (document / screen) and warp it flat."""

    enabled: bool = True
    canny_low: int = 50
    canny_high: int = 150
    min_area_fraction: float = 0.25  # quad must cover >=25% of the image
    epsilon_fraction: float = 0.02  # contour-approximation tightness
    frame_tolerance_px: int = 8  # corners this close to the image edge = canvas frame
    min_corner_deviation_deg: float = 6.0  # skip when quad corners are all within this of 90°


@dataclass
class DenoiseConfig:
    method: str = "fastnlmeans"  # "fastnlmeans" | "bilateral" | "none"
    strength: int = 7
    require_quality_flag: bool = False  # run only when quality flags a defect


@dataclass
class SharpenConfig:
    strength: float = 0.5  # unsharp-mask amount, bounded to [0, 2]
    radius: int = 3
    require_quality_flag: bool = True  # pipeline skips the step unless quality flags blur

    def __post_init__(self) -> None:
        self.strength = float(np.clip(self.strength, 0.0, 2.0))


@dataclass
class ContrastConfig:
    clip_limit: float = 2.0
    tile_grid_size: int = 8
    gamma: float | None = None  # None = no gamma step
    require_quality_flag: bool = False  # run only when quality flags a defect


@dataclass
class GlareConfig:
    """Detect saturated (specular) regions and report their area ratio.

    Glare is flagged, not inpainted: pixels are never hallucinated.
    """

    v_threshold: int = 245
    s_threshold: int = 30


@dataclass
class CropConfig:
    mode: str = "none"  # "none" | "border" | "content"
    border_margin_px: int = 2
    content_threshold: int = 12  # grayscale delta vs border colour


@dataclass
class UpscaleConfig:
    """Bicubic upscaling for small text; optional super-resolution hook."""

    enabled: bool = False
    min_text_height_px: int = 14
    max_factor: float = 3.0


@dataclass
class GlareResult:
    glare_ratio: float
    mask: np.ndarray  # uint8 mask of glare pixels


def rotate(image: np.ndarray, config: RotateConfig) -> tuple[np.ndarray, np.ndarray]:
    """Rotate by an explicit angle. Returns (image, inverse homography)."""
    if config.angle is None or abs(config.angle) < 1e-9:
        return image, IDENTITY.copy()
    height, width = image.shape[:2]
    center = (width / 2.0, height / 2.0)
    matrix = cv2.getRotationMatrix2D(center, config.angle, 1.0)
    cos, sin = abs(matrix[0, 0]), abs(matrix[0, 1])
    new_size = (int(height * sin + width * cos), int(height * cos + width * sin))
    matrix[0, 2] += new_size[0] / 2.0 - center[0]
    matrix[1, 2] += new_size[1] / 2.0 - center[1]
    out = cv2.warpAffine(
        image, matrix, new_size, flags=cv2.INTER_CUBIC, borderValue=(255, 255, 255)
    )
    # OpenCV's rotation matrix maps source->dest; invert for the log.
    return out, _inverse_affine(matrix)


def estimate_orientation_90(image: np.ndarray) -> int:
    """Classify the clockwise rotation (0/90/180/270) needed to restore upright text.

    The Sobel-x row-projection variance separates the text-line direction
    (0/180 vs 90/270) but not the sign, so near-tied opposite candidates are
    tie-broken with the ink-centroid cue: pages anchor content towards the
    top, so the upright candidate has the lower ink-row centroid. Full-frame
    screens/panels have a mid-frame centroid for both candidates, in which
    case the lowest rotation is kept (conservative). A heuristic, not OCR.
    """
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    scores: dict[int, float] = {}
    corrected: dict[int, np.ndarray] = {}
    for degrees in (0, 90, 180, 270):
        rotated = np.ascontiguousarray(np.rot90(gray, k=(4 - degrees // 90) % 4))
        # Vertical text strokes produce an x-gradient concentrated in the rows
        # occupied by text lines, so upright horizontal text maximizes this.
        edges = np.abs(cv2.Sobel(rotated, cv2.CV_32F, 1, 0, ksize=3))
        projection = edges.sum(axis=1)
        scores[degrees] = float(np.var(projection) / (np.mean(projection) + 1e-9))
        corrected[degrees] = np.ascontiguousarray(np.rot90(image, k=(4 - degrees // 90) % 4))

    def centroid_y(degrees: int) -> float:
        # Ink = pixels far from the median gray, so it works on bright pages
        # (dark text on white) and dark screens (bright text on black) alike;
        # a fixed <128 threshold would select the background on dark panels.
        gray_c = cv2.cvtColor(corrected[degrees], cv2.COLOR_RGB2GRAY)
        binary = np.abs(gray_c.astype(np.int16) - int(np.median(gray_c))) > 60
        # Drop frame lines (full-ink rows/cols, e.g. a drawn panel border or a
        # scan edge): they put ink in every row and flatten the centroid to 0.5.
        row_ink = binary.mean(axis=1)
        col_ink = binary.mean(axis=0)
        frame_rows = row_ink > 0.8
        frame_cols = col_ink > 0.8
        binary = binary.copy()
        binary[frame_rows, :] = False
        binary[:, frame_cols] = False
        if not binary.any():
            return 0.5
        rows = np.nonzero(binary.any(axis=1))[0]
        return float(rows.mean()) / binary.shape[0]

    best_score = max(scores.values())
    near_tie = [d for d in scores if scores[d] >= 0.9 * best_score]
    if len(near_tie) == 1:
        return near_tie[0]
    by_centroid = sorted(near_tie, key=centroid_y)
    if centroid_y(by_centroid[1]) - centroid_y(by_centroid[0]) > 0.05:
        return by_centroid[0]
    return min(near_tie)


def _rot90_cw_homography(degrees: int, width: int, height: int) -> np.ndarray:
    """Dest -> src homography for rotating an image clockwise by degrees."""
    if degrees == 90:
        return np.array([[0.0, 1.0, 0.0], [-1.0, 0.0, height - 1.0], [0.0, 0.0, 1.0]])
    if degrees == 180:
        return np.array([[-1.0, 0.0, width - 1.0], [0.0, -1.0, height - 1.0], [0.0, 0.0, 1.0]])
    if degrees == 270:
        return np.array([[0.0, -1.0, width - 1.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]])
    return IDENTITY.copy()


def deskew_angle(image: np.ndarray, max_angle: float = 15.0) -> float:
    """Estimate small skew (degrees, positive = text slopes down to the right)."""
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(gray, 50, 150)
    lines = cv2.HoughLinesP(
        edges,
        1,
        np.pi / 360,
        threshold=30,
        minLineLength=max(40, gray.shape[1] // 12),
        maxLineGap=20,
    )
    if lines is None:
        return 0.0
    angles: list[float] = []
    for x1, y1, x2, y2 in lines.reshape(-1, 4):
        angle = np.degrees(np.arctan2(y2 - y1, x2 - x1))
        if abs(angle) <= max_angle:
            angles.append(angle)
    if not angles:
        return 0.0
    radians = np.arctan2(np.sin(np.radians(angles)), np.cos(np.radians(angles)))
    median = float(np.degrees(np.median(radians)))
    return median


def correct_orientation(
    image: np.ndarray, config: OrientationConfig
) -> tuple[np.ndarray, np.ndarray, dict[str, float | int | str | bool]]:
    """Fix 90-degree orientation and small skew. Returns (image, homography, info)."""
    homography = IDENTITY.copy()
    info: dict[str, float | int | str | bool] = {}

    if config.detect:
        degrees = estimate_orientation_90(image)
        info["orientation_90"] = degrees
        if degrees:
            height, width = image.shape[:2]
            image = np.ascontiguousarray(np.rot90(image, k=(4 - degrees // 90) % 4))
            homography = _rot90_cw_homography(degrees, width, height) @ homography

    if config.deskew:
        angle = deskew_angle(image)
        info["skew_deg"] = round(angle, 3)
        if abs(angle) > 0.05 and abs(angle) <= config.max_correction_angle:
            height, width = image.shape[:2]
            center = (width / 2.0, height / 2.0)
            matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
            cos, sin = abs(matrix[0, 0]), abs(matrix[0, 1])
            new_size = (int(height * sin + width * cos), int(height * cos + width * sin))
            matrix[0, 2] += new_size[0] / 2.0 - center[0]
            matrix[1, 2] += new_size[1] / 2.0 - center[1]
            image = cv2.warpAffine(
                image, matrix, new_size, flags=cv2.INTER_CUBIC, borderValue=(255, 255, 255)
            )
            homography = _inverse_affine(matrix) @ homography
    return image, homography, info


def order_corners(corners: np.ndarray) -> np.ndarray:
    """Order 4 (x, y) points as top-left, top-right, bottom-right, bottom-left."""
    pts = np.asarray(corners, dtype=np.float32)
    s = pts.sum(axis=1)
    d = np.diff(pts, axis=1).ravel()
    return np.array(
        [pts[np.argmin(s)], pts[np.argmin(d)], pts[np.argmax(s)], pts[np.argmax(d)]],
        dtype=np.float32,
    )


def _is_frame_quad(quad: np.ndarray, width: int, height: int, tolerance_px: int) -> bool:
    """True when every corner hugs the image border: the canvas edge, not content."""
    xs, ys = quad[:, 0], quad[:, 1]
    return bool(
        np.all(
            (xs <= tolerance_px)
            | (xs >= width - 1 - tolerance_px)
            | (ys <= tolerance_px)
            | (ys >= height - 1 - tolerance_px)
        )
    )


def quad_corner_deviation_deg(quad: np.ndarray) -> float:
    """Largest deviation from 90° across the quad's interior corners."""
    pts = quad.astype(np.float64)
    worst = 0.0
    for i in range(4):
        prev, center, nxt = pts[(i - 1) % 4], pts[i], pts[(i + 1) % 4]
        v1, v2 = prev - center, nxt - center
        cos = float(np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2)))
        worst = max(worst, abs(np.degrees(np.arccos(np.clip(cos, -1.0, 1.0))) - 90.0))
    return worst


def detect_quadrilateral(image: np.ndarray, config: PerspectiveConfig) -> np.ndarray | None:
    """Largest *inner* content quad: Canny contours, then Otsu threshold fallback.

    Quads that hug the image border (the canvas / scan frame) are rejected so
    the detector locks onto the panel or document instead of the frame line.
    """
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    height, width = image.shape[:2]
    image_area = height * width
    for edge_map in (
        canny := cv2.dilate(
            cv2.Canny(blurred, config.canny_low, config.canny_high), np.ones((3, 3), np.uint8)
        ),
        # Glare blows out stretches of the screen border, leaving the Canny
        # contour broken into arcs that never approximate to a convex quad.
        # Closing bridges those gaps so the quad survives a photographed
        # screen; frame-quads are still rejected by _is_frame_quad below.
        cv2.morphologyEx(canny, cv2.MORPH_CLOSE, np.ones((25, 25), np.uint8)),
        cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1],
    ):
        contours, _ = cv2.findContours(edge_map, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        candidates: list[tuple[float, np.ndarray]] = []
        for contour in contours:
            area = cv2.contourArea(contour)
            if area < config.min_area_fraction * image_area:
                continue
            per = cv2.arcLength(contour, True)
            for eps in (0.01, 0.02, 0.03, 0.05, 0.08, 0.1):
                approx = cv2.approxPolyDP(contour, eps * per, True)
                if len(approx) == 4 and cv2.isContourConvex(approx):
                    quad = order_corners(approx.reshape(4, 2))
                    if not _is_frame_quad(quad, width, height, config.frame_tolerance_px):
                        candidates.append((area, quad))
                    break
        if candidates:
            return max(candidates, key=lambda item: item[0])[1]
    return None


def correct_perspective(
    image: np.ndarray, config: PerspectiveConfig
) -> tuple[np.ndarray, np.ndarray, np.ndarray | None, bool]:
    """Warp the detected document/screen quad to a rectangle.

    Returns (image, inverse homography for the log, detected quad, corrected).
    When no sufficiently large quad is found the image is returned unchanged.
    """
    if not config.enabled:
        return image, IDENTITY.copy(), None, False
    quad = detect_quadrilateral(image, config)
    if quad is None:
        return image, IDENTITY.copy(), None, False
    width_top = np.linalg.norm(quad[1] - quad[0])
    width_bottom = np.linalg.norm(quad[2] - quad[3])
    height_left = np.linalg.norm(quad[3] - quad[0])
    height_right = np.linalg.norm(quad[2] - quad[1])
    out_w = int(max(width_top, width_bottom))
    out_h = int(max(height_left, height_right))
    if out_w < 8 or out_h < 8:
        return image, IDENTITY.copy(), None, False
    destination = np.array(
        [[0, 0], [out_w - 1, 0], [out_w - 1, out_h - 1], [0, out_h - 1]], dtype=np.float32
    )
    forward = cv2.getPerspectiveTransform(quad, destination)
    out = cv2.warpPerspective(image, forward, (out_w, out_h), flags=cv2.INTER_CUBIC)
    return out, np.linalg.inv(forward), quad, True


def denoise(image: np.ndarray, config: DenoiseConfig) -> np.ndarray:
    if config.method == "none" or config.strength <= 0:
        return image
    if config.method == "bilateral":
        return cv2.bilateralFilter(image, 9, config.strength * 5, config.strength * 5)
    return cv2.fastNlMeansDenoisingColored(image, None, config.strength, config.strength, 7, 21)


def sharpen(image: np.ndarray, config: SharpenConfig) -> np.ndarray:
    if config.strength <= 0:
        return image
    blur = cv2.GaussianBlur(image, (0, 0), config.radius)
    return cv2.addWeighted(image, 1.0 + config.strength, blur, -config.strength, 0)


def enhance_contrast(image: np.ndarray, config: ContrastConfig) -> np.ndarray:
    out = image
    lab = cv2.cvtColor(out, cv2.COLOR_RGB2LAB)
    l_channel, a_channel, b_channel = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=config.clip_limit, tileGridSize=(config.tile_grid_size,) * 2)
    l_channel = clahe.apply(l_channel)
    out = cv2.cvtColor(cv2.merge([l_channel, a_channel, b_channel]), cv2.COLOR_LAB2RGB)
    if config.gamma is not None and config.gamma > 0:
        table = ((np.arange(256) / 255.0) ** (1.0 / config.gamma) * 255).astype(np.uint8)
        out = cv2.LUT(out, table)
    return out


def detect_glare(image: np.ndarray, config: GlareConfig) -> GlareResult:
    hsv = cv2.cvtColor(image, cv2.COLOR_RGB2HSV)
    bright = hsv[:, :, 2] >= config.v_threshold
    unsat = hsv[:, :, 1] <= config.s_threshold
    mask = (bright & unsat).astype(np.uint8)
    return GlareResult(glare_ratio=float(mask.mean()), mask=mask * 255)


def trim_borders(image: np.ndarray, config: CropConfig) -> tuple[np.ndarray, np.ndarray]:
    """Crop transforms return (image, post->pre homography for TransformLog.add)."""
    if config.mode == "none":
        return image, IDENTITY.copy()
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    if config.mode == "border":
        border_colour = int(np.median(np.concatenate([gray[0], gray[-1], gray[:, 0], gray[:, -1]])))
        off_border = np.abs(gray.astype(np.int16) - border_colour) > config.content_threshold
        mask = off_border.astype(np.uint8)
    else:  # "content"
        mask = (gray < 255 - config.content_threshold).astype(np.uint8)
    rows = np.any(mask, axis=1)
    cols = np.any(mask, axis=0)
    if not rows.any() or not cols.any():
        return image, IDENTITY.copy()
    top = max(int(np.argmax(rows)) - config.border_margin_px, 0)
    last_row = gray.shape[0] - int(np.argmax(rows[::-1])) + config.border_margin_px
    bottom = min(last_row, gray.shape[0])
    left = max(int(np.argmax(cols)) - config.border_margin_px, 0)
    last_col = gray.shape[1] - int(np.argmax(cols[::-1])) + config.border_margin_px
    right = min(last_col, gray.shape[1])
    if bottom - top < 8 or right - left < 8:
        return image, IDENTITY.copy()
    matrix = np.array([[1.0, 0.0, float(left)], [0.0, 1.0, float(top)]], dtype=np.float64)
    return image[top:bottom, left:right], _homography_from_affine(matrix)


def crop_region(image: np.ndarray, roi: tuple[int, int, int, int]) -> tuple[np.ndarray, np.ndarray]:
    """Region-of-interest crop (x, y, w, h) for later multi-scale OCR."""
    x, y, w, h = roi
    height, width = image.shape[:2]
    x, y = max(0, x), max(0, y)
    w, h = min(w, width - x), min(h, height - y)
    matrix = np.array([[1.0, 0.0, float(x)], [0.0, 1.0, float(y)]], dtype=np.float64)
    return image[y : y + h, x : x + w], _homography_from_affine(matrix)


def estimate_text_height(image: np.ndarray) -> float:
    """Median text stroke-run height estimate from horizontal projection valleys."""
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    binary = cv2.adaptiveThreshold(
        cv2.GaussianBlur(gray, (3, 3), 0),
        255,
        cv2.ADAPTIVE_THRESH_MEAN_C,
        cv2.THRESH_BINARY_INV,
        15,
        10,
    )
    projection = binary.sum(axis=1)
    peak = float(projection.max(axis=0))
    threshold = peak * 0.25 if peak else 0
    runs: list[int] = []
    run = 0
    for value in projection:
        if value > threshold:
            run += 1
        elif run:
            runs.append(run)
            run = 0
    if run:
        runs.append(run)
    return float(np.median(runs)) if runs else 0.0


def upscale(image: np.ndarray, config: UpscaleConfig) -> tuple[np.ndarray, np.ndarray, float]:
    """Bicubic upscale when the estimated text height is too small for OCR."""
    if not config.enabled:
        return image, IDENTITY.copy(), 1.0
    text_height = estimate_text_height(image)
    if text_height <= 0 or text_height >= config.min_text_height_px:
        return image, IDENTITY.copy(), 1.0
    ratio = config.min_text_height_px / max(text_height, 1.0)
    factor = float(np.clip(ratio, 1.0, config.max_factor))
    out = cv2.resize(image, None, fx=factor, fy=factor, interpolation=cv2.INTER_CUBIC)
    matrix = np.array([[factor, 0.0, 0.0], [0.0, factor, 0.0]], dtype=np.float64)
    return out, _inverse_affine(matrix), factor
