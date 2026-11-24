"""Vision-assist model hook (P4 item 3, interface only).

Defines how an external detector (or future VLM) would be plugged into the
industrial pipeline. P4 ships the interface and an unavailable stub only —
no model is downloaded or evaluated.
"""

from __future__ import annotations

import numpy as np

from engine.industrial.regions import DetectorModelHook, Region, UnavailableDetectorHook

__all__ = ["DetectorModelHook", "Region", "UnavailableDetectorHook", "VisionAssistHook"]


class VisionAssistHook(DetectorModelHook):
    """Optional external vision-assist proposal hook (stub, never downloads).

    A concrete implementation would return Region proposals in pixel
    coordinates. The pipeline marks them ``source="model"`` and still
    requires OCR/pixel support before accepting them.
    """

    def __init__(self, detector=None) -> None:
        self._detector = detector

    @property
    def available(self) -> bool:
        return self._detector is not None

    def detect(self, image: np.ndarray) -> list[Region]:
        if self._detector is None:
            return []
        raise RuntimeError("vision-assist detector not configured; interface stub only")
