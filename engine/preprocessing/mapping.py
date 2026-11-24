"""Coordinate traceability: ordered TransformLog with a cumulative homography.

Every geometry-changing step contributes a 3x3 homography H_step mapping
processed coordinates back to the previous step's coordinates. The log keeps
the cumulative matrix H = H_1 @ H_2 @ ... (processed -> original), so
map_to_original(points) is a single matrix application and
map_to_processed(points) uses the exact inverse. Round-trip error is float
precision (< 2 px by construction).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

# Identity 3x3 homography.
IDENTITY = np.eye(3, dtype=np.float64)


def apply_homography(points: np.ndarray, homography: np.ndarray) -> np.ndarray:
    """Apply a 3x3 homography to an (N,2) array (or (2,) vector) of points."""
    pts = np.asarray(points, dtype=np.float64)
    single = pts.ndim == 1
    pts = np.atleast_2d(pts)
    ones = np.concatenate([pts, np.ones((len(pts), 1))], axis=1)
    projected = ones @ homography.T
    projected = projected[:, :2] / projected[:, 2:3]
    return projected[0] if single else projected


@dataclass
class TransformEntry:
    """One recorded transform step."""

    name: str
    matrix: np.ndarray  # 3x3, maps post-step coords -> pre-step coords
    params: dict[str, float | int | str | bool] = field(default_factory=dict)


@dataclass
class TransformLog:
    """Ordered record of geometry-changing transforms with coordinate mapping."""

    entries: list[TransformEntry] = field(default_factory=list)
    _cumulative: np.ndarray = field(default_factory=lambda: IDENTITY.copy())

    def add(self, name: str, matrix: np.ndarray, **params: object) -> None:
        """Record a step whose matrix maps post-step coords to pre-step coords.

        The cumulative matrix is H_new @ H_old so that it always maps the
        latest processed coordinates back to the original image.
        """
        matrix = np.asarray(matrix, dtype=np.float64)
        self.entries.append(
            TransformEntry(name=name, matrix=matrix, params=dict(params))  # type: ignore[arg-type]
        )
        self._cumulative = matrix @ self._cumulative

    @property
    def homography(self) -> np.ndarray:
        """Cumulative processed -> original homography."""
        return self._cumulative.copy()

    def map_to_original(self, points: np.ndarray) -> np.ndarray:
        return apply_homography(points, self._cumulative)

    def map_to_processed(self, points: np.ndarray) -> np.ndarray:
        inverse = np.linalg.inv(self._cumulative)
        return apply_homography(points, inverse)

    def round_trip_error(self, points: np.ndarray) -> float:
        forward = self.map_to_original(points)
        back = self.map_to_processed(forward)
        return float(np.max(np.linalg.norm(np.asarray(points) - back, axis=-1)))
