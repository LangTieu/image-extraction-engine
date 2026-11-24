"""Quality metrics that gate and report preprocessing decisions."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

import cv2
import numpy as np

from engine.preprocessing.transforms import estimate_text_height


class QualityWarning(StrEnum):
    LOW_RESOLUTION = "low_resolution"
    BLURRY = "blurry"
    TOO_DARK = "too_dark"
    TOO_BRIGHT = "too_bright"
    LOW_CONTRAST = "low_contrast"
    SKEWED = "skewed"
    GLARE_DETECTED = "glare_detected"
    TEXT_TOO_SMALL = "text_too_small"


@dataclass
class QualityReport:
    width: int
    height: int
    blur_variance: float  # Laplacian variance; < 100 flags blurry
    brightness: float  # mean gray, 0-255; outside [60, 220] flags
    contrast: float  # std of gray; < 35 flags
    glare_ratio: float  # fraction of saturated pixels; > 0.05 flags
    skew_angle_deg: float  # |angle| > 5 flags
    estimated_text_height_px: float  # < 10 flags
    warnings: list[str] = field(default_factory=list)

    @property
    def routing_hint(self) -> str:
        """Suggest the router category from measurable input quality."""
        if QualityWarning.GLARE_DETECTED in self.warnings:
            return "industrial_screen_photo"
        if (
            QualityWarning.LOW_RESOLUTION in self.warnings
            or QualityWarning.TEXT_TOO_SMALL in self.warnings
        ):
            return "upscale_required"
        if QualityWarning.SKEWED in self.warnings or QualityWarning.BLURRY in self.warnings:
            return "photographed_document"
        return "clean_input"


def compute_quality(image: np.ndarray, glare_ratio: float = 0.0) -> QualityReport:
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    height, width = gray.shape[:2]
    report = QualityReport(
        width=int(width),
        height=int(height),
        blur_variance=float(cv2.Laplacian(gray, cv2.CV_64F).var()),
        brightness=float(gray.mean()),
        contrast=float(gray.std()),
        glare_ratio=float(glare_ratio),
        skew_angle_deg=0.0,
        estimated_text_height_px=round(estimate_text_height(image), 2),
    )
    if min(report.width, report.height) < 640:
        report.warnings.append(QualityWarning.LOW_RESOLUTION)
    if report.blur_variance < 100.0:
        report.warnings.append(QualityWarning.BLURRY)
    if report.brightness < 60.0:
        report.warnings.append(QualityWarning.TOO_DARK)
    elif report.brightness > 220.0:
        report.warnings.append(QualityWarning.TOO_BRIGHT)
    if report.contrast < 35.0:
        report.warnings.append(QualityWarning.LOW_CONTRAST)
    if report.glare_ratio > 0.05:
        report.warnings.append(QualityWarning.GLARE_DETECTED)
    if report.estimated_text_height_px > 0 and report.estimated_text_height_px < 10.0:
        report.warnings.append(QualityWarning.TEXT_TOO_SMALL)
    return report


def add_skew_warning(report: QualityReport, angle_deg: float) -> QualityReport:
    if abs(angle_deg) > 5.0:
        report.warnings.append(QualityWarning.SKEWED)
    report.skew_angle_deg = round(angle_deg, 3)
    return report
