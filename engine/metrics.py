"""Reference implementations of the P0 metric definitions.

Formulas and normalization rules are documented in docs/spec/metrics.md.
These are real, tested implementations for the string metrics; table
structure accuracy is an adjacency-F1 reference implementation. Vision-model
or OCR backends are plugged in later phases; the metric layer is stable.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field


def _normalize_for_cer(text: str) -> str:
    """Normalize text for CER: NFC-ish strip, collapse whitespace, lowercase."""
    text = text.strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        cur = [i]
        for j, cb in enumerate(b, start=1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def cer(reference: str, hypothesis: str) -> float:
    """Character Error Rate = edit distance / reference length.

    Normalization: strip, lowercase, collapse whitespace. If the reference is
    empty, CER is 0 when the hypothesis is also empty and 1 otherwise.
    """
    ref, hyp = _normalize_for_cer(reference), _normalize_for_cer(hypothesis)
    if not ref:
        return 0.0 if not hyp else 1.0
    return _levenshtein(ref, hyp) / len(ref)


def wer(reference: str, hypothesis: str) -> float:
    """Word Error Rate = word-level edit distance / reference word count."""
    ref = _normalize_for_cer(reference).split()
    hyp = _normalize_for_cer(hypothesis).split()
    if not ref:
        return 0.0 if not hyp else 1.0
    prev = list(range(len(hyp) + 1))
    for i, wr in enumerate(ref, start=1):
        cur = [i]
        for j, wh in enumerate(hyp, start=1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (wr != wh)))
        prev = cur
    return prev[-1] / len(ref)


def _adjacency(cells: set[tuple[int, int]]) -> set[tuple[tuple[int, int], tuple[int, int]]]:
    """All directed neighbour pairs within a set of (row, col) cells."""
    cell_set = set(cells)
    out: set[tuple[tuple[int, int], tuple[int, int]]] = set()
    for r, c in cell_set:
        for dr, dc in ((0, 1), (1, 0)):
            if (r + dr, c + dc) in cell_set:
                out.add(((r, c), (r + dr, c + dc)))
    return out


@dataclass
class TableStructureResult:
    precision: float
    recall: float
    f1: float


@dataclass
class TableComparison:
    """Minimal cell-position comparison backing Table Structure Accuracy."""

    correct_cells: int = 0
    missing_cells: int = 0
    extra_cells: int = 0
    adjacency: TableStructureResult = field(
        default_factory=lambda: TableStructureResult(0.0, 0.0, 0.0)
    )


def table_structure_accuracy(
    reference_cells: Sequence[tuple[int, int]],
    predicted_cells: Sequence[tuple[int, int]],
) -> TableComparison:
    """Cell-adjacency F1 based Table Structure Accuracy (TEDS-lite).

    A predicted cell is correct if the same (row, col) exists in the
    reference; adjacency F1 compares neighbour pairs, which captures merged
    and misaligned rows/columns without needing cell text.
    """
    ref_set, pred_set = set(reference_cells), set(predicted_cells)
    ref_adj, pred_adj = _adjacency(ref_set), _adjacency(pred_set)
    tp = len(ref_adj & pred_adj)
    precision = tp / len(pred_adj) if pred_adj else 0.0
    recall = tp / len(ref_adj) if ref_adj else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return TableComparison(
        correct_cells=len(ref_set & pred_set),
        missing_cells=len(ref_set - pred_set),
        extra_cells=len(pred_set - ref_set),
        adjacency=TableStructureResult(precision, recall, f1),
    )


def field_accuracy(
    reference: dict[str, str | float | int],
    predicted: dict[str, str | float | int],
    *,
    numeric_tolerance: float = 1e-6,
) -> float:
    """Fraction of reference fields whose predicted value matches exactly
    (strings, case-normalized) or within tolerance (numbers)."""
    if not reference:
        return 1.0
    hits = 0
    for key, ref_value in reference.items():
        if key not in predicted:
            continue
        pred_value = predicted[key]
        if isinstance(ref_value, (int, float)) and not isinstance(ref_value, bool):
            try:
                if abs(float(pred_value) - float(ref_value)) <= numeric_tolerance:
                    hits += 1
            except (TypeError, ValueError):
                continue
        elif str(pred_value).strip().lower() == str(ref_value).strip().lower():
            hits += 1
    return hits / len(reference)


def coil_id_accuracy(
    reference: dict[str, str],
    predicted: dict[str, str],
) -> float:
    """Exact-match rate for coil identifiers (HOT_COIL_NO / COLD_COIL_NO).

    Normalization for IDs: uppercase, remove spaces and separators so that
    'h123-45' and 'H12345' compare equal.
    """

    def norm(v: str) -> str:
        return re.sub(r"[\s\-_]", "", v).upper()

    if not reference:
        return 1.0
    hits = sum(1 for k, v in reference.items() if k in predicted and norm(predicted[k]) == norm(v))
    return hits / len(reference)


def processing_time(durations_ms: Sequence[float]) -> dict[str, float]:
    """Per-image mean/p95 latency in ms; batch time is the sum."""
    if not durations_ms:
        return {"mean_ms": 0.0, "p95_ms": 0.0, "batch_ms": 0.0}
    ordered = sorted(durations_ms)

    def p95(values: list[float]) -> float:
        idx = max(0, round(0.95 * (len(values) - 1)))
        return values[idx]

    return {
        "mean_ms": sum(ordered) / len(ordered),
        "p95_ms": p95(ordered),
        "batch_ms": float(sum(ordered)),
    }
