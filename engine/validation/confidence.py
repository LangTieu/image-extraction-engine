"""Confidence model and calibration (P5 item 5).

A field's confidence combines the available signals: OCR token confidence,
table-cell confidence, image quality, rule outcomes and cross-check
agreement. Aggregate confidences roll up cell → table → document.

Calibration maps raw scores to calibrated probabilities: Platt (logistic)
and isotonic (PAVA) are implemented on numpy only. Expected Calibration
Error (ECE) and reliability-diagram bins support the evaluation on the
benchmark seed set.
"""

from __future__ import annotations

import numpy as np

# Signal weights: OCR/cell evidence dominates; quality and rules modulate.
_WEIGHTS = {"ocr": 0.45, "cell": 0.4, "quality": 0.15, "rules": 0.5, "agreement": 0.35}


def field_confidence(
    *,
    ocr_confidence: float | None = None,
    cell_confidence: float | None = None,
    image_quality: float | None = None,
    rule_ok: bool | None = None,
    agreement: float | None = None,
    n_errors: int = 0,
    n_warnings: int = 0,
) -> float:
    """Weighted combination of the available signals, in [0, 1].

    Signals that are absent simply don't contribute (weights renormalize);
    error-severity findings push the score down hard.
    """
    contributions: list[tuple[float, float]] = []
    if ocr_confidence is not None:
        contributions.append((_WEIGHTS["ocr"], float(ocr_confidence)))
    if cell_confidence is not None:
        contributions.append((_WEIGHTS["cell"], float(cell_confidence)))
    if image_quality is not None:
        contributions.append((_WEIGHTS["quality"], float(image_quality)))
    if rule_ok is not None:
        contributions.append((_WEIGHTS["rules"], 1.0 if rule_ok else 0.25))
    if agreement is not None:
        contributions.append((_WEIGHTS["agreement"], float(agreement)))
    if not contributions:
        base = 0.5
    else:
        total_w = sum(w for w, _ in contributions)
        base = sum(w * v for w, v in contributions) / total_w
    base *= float(np.exp(-0.9 * n_errors)) * float(np.exp(-0.25 * n_warnings))
    return float(min(1.0, max(0.0, base)))


def aggregate_confidence(values: list[float | None]) -> float | None:
    """Mean of the non-None values; None when nothing is measurable."""
    xs = [v for v in values if v is not None]
    if not xs:
        return None
    return float(sum(xs) / len(xs))


def table_confidence(cells: list[float | None]) -> float | None:
    return aggregate_confidence(cells)


def doc_confidence(
    field_confidences: list[float | None], table_confidences: list[float | None]
) -> float | None:
    return aggregate_confidence(field_confidences + table_confidences)


class PlattCalibrator:
    """Logistic calibration a*logit(s)+b, fit by gradient descent."""

    def __init__(self) -> None:
        self.a = 1.0
        self.b = 0.0

    def fit(self, scores: list[float], correct: list[bool], epochs: int = 500) -> PlattCalibrator:
        s = _eps(np.asarray(scores, dtype=float))
        y = np.asarray(correct, dtype=float)
        a, b = 1.0, 0.0
        lr = 0.1
        for _ in range(epochs):
            p = 1.0 / (1.0 + np.exp(-(a * np.log(s / (1 - s)) + b)))
            ga = np.mean((p - y) * np.log(s / (1 - s)))
            gb = np.mean(p - y)
            a -= lr * ga
            b -= lr * gb
        self.a, self.b = float(a), float(b)
        return self

    def __call__(self, scores: list[float]) -> list[float]:
        s = _eps(np.asarray(scores, dtype=float))
        z = self.a * np.log(s / (1 - s)) + self.b
        return list(1.0 / (1.0 + np.exp(-z)))


class IsotonicCalibrator:
    """Isotonic regression via pool-adjacent-violators, then step interpolation."""

    def __init__(self) -> None:
        self.x: np.ndarray | None = None
        self.y: np.ndarray | None = None

    def fit(self, scores: list[float], correct: list[bool]) -> IsotonicCalibrator:
        x = np.asarray(scores, dtype=float)
        y = np.asarray(correct, dtype=float)
        order = np.argsort(x, kind="stable")
        x, y = x[order], y[order]
        blocks: list[list[float]] = []  # [weight, mean]
        for xi, yi in zip(x, y, strict=True):
            blocks.append([1.0, float(yi)])
            while len(blocks) > 1 and blocks[-1][1] < blocks[-2][1]:
                w1, m1 = blocks.pop()
                w2, m2 = blocks.pop()
                blocks.append([w1 + w2, (w1 * m1 + w2 * m2) / (w1 + w2)])
        xs, ys, acc = [], [], 0
        for w, m in blocks:
            n = int(round(w))
            xs.append(float(np.mean(x[acc : acc + n])))
            ys.append(m)
            acc += n
        self.x, self.y = np.asarray(xs), np.asarray(ys)
        return self

    def __call__(self, scores: list[float]) -> list[float]:
        if self.x is None or self.y is None or not scores:
            return list(scores)
        idx = np.searchsorted(self.x, np.asarray(scores, dtype=float), side="right") - 1
        idx = np.clip(idx, 0, len(self.y) - 1)
        return [float(self.y[i]) for i in idx]


def ece(scores: list[float], correct: list[bool], n_bins: int = 10) -> float:
    """Expected Calibration Error: mean |accuracy - confidence| per bin."""
    return reliability_diagram(scores, correct, n_bins)[-1]["ece"]


def reliability_diagram(
    scores: list[float], correct: list[bool], n_bins: int = 10
) -> list[dict[str, float]]:
    if not scores:
        return [{"ece": 0.0}]
    s = np.asarray(scores, dtype=float)
    y = np.asarray(correct, dtype=float)
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    bins: list[dict[str, float]] = []
    ece_total = 0.0
    for i in range(n_bins):
        lo, hi = edges[i], edges[i + 1]
        mask = (s >= lo) & (s < hi) if i < n_bins - 1 else (s >= lo) & (s <= hi)
        n = int(mask.sum())
        if n == 0:
            bins.append(
                {
                    "bin_low": lo,
                    "bin_high": hi,
                    "count": 0,
                    "mean_predicted": 0.0,
                    "fraction_correct": 0.0,
                    "gap": 0.0,
                }
            )
            continue
        mp = float(s[mask].mean())
        fc = float(y[mask].mean())
        gap = abs(mp - fc)
        ece_total += gap * n / len(s)
        bins.append(
            {
                "bin_low": lo,
                "bin_high": hi,
                "count": n,
                "mean_predicted": mp,
                "fraction_correct": fc,
                "gap": gap,
            }
        )
    bins.append({"ece": ece_total})
    return bins


def _eps(a: np.ndarray) -> np.ndarray:
    return np.clip(a, 1e-6, 1 - 1e-6)
