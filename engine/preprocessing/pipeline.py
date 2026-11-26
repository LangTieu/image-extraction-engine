"""YAML-driven preprocessing pipeline with named profiles.

Profiles are plain dictionaries in engine/preprocessing/profiles/*.yaml:

    name: screenshot
    steps:
      contrast: {clip_limit: 2.0}
      glare: {}

Every enabled step runs in the fixed order below (from docs/spec:
orientation -> perspective -> crop -> denoise -> contrast -> sharpen ->
upscale). Geometry steps contribute to the cumulative TransformLog homography.
Known limitation: steps are appended in YAML key order (Python dicts keep
insertion order), but execution order is fixed by run(), so profile YAMLs
cannot reorder the pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from engine.preprocessing import transforms as tx
from engine.preprocessing.mapping import TransformLog
from engine.preprocessing.quality import (
    QualityReport,
    QualityWarning,
    add_skew_warning,
    compute_quality,
)

PROFILE_ORDER = [
    "rotate",
    "orientation",
    "perspective",
    "crop",
    "denoise",
    "contrast",
    "sharpen",
    "upscale",
]


def _blur_defect(quality: QualityReport) -> bool:
    """True when quality flags a defect sharpening could fix."""
    return bool(
        QualityWarning.BLURRY in quality.warnings or QualityWarning.LOW_CONTRAST in quality.warnings
    )


def _tone_defect(quality: QualityReport) -> bool:
    """True when quality flags noise/contrast a denoise+contrast pass helps.

    Dark or low-contrast photos (screen shots of HMIs) carry sensor/JPEG
    noise and crushed contrast; the enhancement steps are wasted on clean
    images, which the gate keeps untouched.
    """
    return bool(
        {QualityWarning.BLURRY, QualityWarning.LOW_CONTRAST, QualityWarning.TOO_DARK}
        & set(quality.warnings)
    )


@dataclass
class PreprocessedImage:
    image: np.ndarray  # RGB uint8
    transform_log: TransformLog
    quality_before: QualityReport
    quality_after: QualityReport
    profile_name: str
    perspective_quad_original: np.ndarray | None = None  # in original coordinates
    glare_ratio_before: float = 0.0
    step_info: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass
class PreprocessingPipeline:
    profile_name: str
    steps: dict[str, dict[str, Any]]

    @classmethod
    def from_dict(
        cls, profile_name: str, steps: dict[str, dict[str, Any]]
    ) -> PreprocessingPipeline:
        unknown = set(steps) - set(PROFILE_ORDER)
        if unknown:
            raise ValueError(f"unknown preprocessing steps: {sorted(unknown)}")
        return cls(
            profile_name=profile_name, steps={name: dict(params) for name, params in steps.items()}
        )

    @classmethod
    def from_yaml(cls, path: str | Path) -> PreprocessingPipeline:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        return cls.from_dict(raw.get("name", Path(path).stem), raw.get("steps", {}) or {})

    @classmethod
    def from_options(cls, options) -> PreprocessingPipeline:
        """Build from ``engine.options.PreprocessOptions``.

        The overrides are the steps, passed through ``from_dict`` exactly as
        the worker always passed them (they replace, not merge, the profile's
        steps); the profile name only labels the run and is validated by
        ``PreprocessOptions``.
        """
        return cls.from_dict(
            options.profile, {k: dict(v) for k, v in options.overrides.items()}
        )

    @classmethod
    def bundled_profiles(cls) -> list[str]:
        """Names of the bundled profiles in engine/preprocessing/profiles/."""
        return sorted(
            p.name[: -len(".yaml")]
            for p in resources.files("engine.preprocessing").joinpath("profiles").iterdir()
            if p.name.endswith(".yaml")
        )

    @classmethod
    def for_profile(cls, name: str) -> PreprocessingPipeline:
        """Load a bundled profile from engine/preprocessing/profiles/."""
        resource = resources.files("engine.preprocessing").joinpath(f"profiles/{name}.yaml")
        if not resource.is_file():
            raise FileNotFoundError(f"no bundled preprocessing profile named {name!r}")
        return cls.from_yaml(str(resource))

    def run(self, image: np.ndarray) -> PreprocessedImage:
        working = image.copy()
        log = TransformLog()
        info: dict[str, dict[str, Any]] = {}

        glare = tx.detect_glare(image, tx.GlareConfig())
        quality_before = compute_quality(image, glare_ratio=glare.glare_ratio)
        quality_before = add_skew_warning(quality_before, tx.deskew_angle(image))
        glare_ratio_before = glare.glare_ratio

        params = self.steps.get("rotate")
        if params:
            working, matrix = tx.rotate(working, tx.RotateConfig(**params))
            angle = float(params["angle"]) if params.get("angle") is not None else 0.0
            log.add("rotate", matrix, angle=angle)

        params = self.steps.get("orientation")
        if params:
            cfg = tx.OrientationConfig(**params)
            working, matrix, orient_info = tx.correct_orientation(working, cfg)
            log.add("orientation", matrix, **orient_info)
            info["orientation"] = orient_info
            skew = float(orient_info.get("skew_deg", 0.0))
            quality_before = add_skew_warning(quality_before, skew)

        params = self.steps.get("perspective")
        quad_original = None
        if params:
            config = tx.PerspectiveConfig(**params)
            quad = tx.detect_quadrilateral(working, config)
            if quad is None or tx.quad_corner_deviation_deg(quad) < config.min_corner_deviation_deg:
                info["perspective"] = {
                    "skipped": "quality gate: no perspective-distorted content quad found"
                }
            else:
                working, matrix, quad, corrected = tx.correct_perspective(working, config)
                log.add("perspective", matrix, corrected=corrected)
                info["perspective"] = {"corrected": corrected}
                if corrected and quad is not None:
                    quad_original = log.map_to_original(quad.astype(np.float64))
                    info["perspective"]["quad_original"] = quad_original.tolist()

        params = self.steps.get("crop")
        if params:
            working, matrix = tx.trim_borders(working, tx.CropConfig(**params))
            log.add("crop", matrix, mode=params.get("mode", "none"))

        params = self.steps.get("denoise")
        if params:
            dn_cfg = tx.DenoiseConfig(**params)
            if dn_cfg.require_quality_flag and not _tone_defect(quality_before):
                info["denoise"] = {"skipped": "quality gate: no noise/tone defect flagged"}
            else:
                working = tx.denoise(working, dn_cfg)
                info["denoise"] = dict(params)

        params = self.steps.get("contrast")
        if params:
            ct_cfg = tx.ContrastConfig(**params)
            if ct_cfg.require_quality_flag and not _tone_defect(quality_before):
                info["contrast"] = {"skipped": "quality gate: no tone/contrast defect flagged"}
            else:
                working = tx.enhance_contrast(working, ct_cfg)
                info["contrast"] = dict(params)

        params = self.steps.get("sharpen")
        if params:
            sharpen_cfg = tx.SharpenConfig(**params)
            if sharpen_cfg.require_quality_flag and not _blur_defect(quality_before):
                info["sharpen"] = {"skipped": "quality gate: no blur/contrast defect flagged"}
            else:
                working = tx.sharpen(working, sharpen_cfg)
                info["sharpen"] = dict(params)

        params = self.steps.get("upscale")
        if params:
            working, matrix, factor = tx.upscale(working, tx.UpscaleConfig(**params))
            log.add("upscale", matrix, factor=factor)
            info["upscale"] = {"factor": factor}

        return self._finish(working, log, quality_before, info, quad_original, glare_ratio_before)

    def _finish(
        self,
        working: np.ndarray,
        log: TransformLog,
        quality_before: QualityReport,
        info: dict[str, dict[str, Any]],
        quad_original: np.ndarray | None,
        glare_ratio_before: float,
    ) -> PreprocessedImage:
        quality_after = compute_quality(working, glare_ratio=glare_ratio_before)
        return PreprocessedImage(
            image=working,
            transform_log=log,
            quality_before=quality_before,
            quality_after=quality_after,
            profile_name=self.profile_name,
            perspective_quad_original=quad_original,
            glare_ratio_before=glare_ratio_before,
            step_info=info,
        )
