"""Reading-order reconstruction: tokens -> text blocks with column handling.

Columns are detected first (gaps in the horizontal coverage of token bboxes),
then tokens are grouped into horizontal lines within each column. Columns are
ordered left-to-right, lines top-to-bottom; a ``reading_order`` int (0-based,
one per line) is stored on every block.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from engine.ocr.base import OCRToken


@dataclass
class TextBlock:
    text: str
    bbox: tuple[float, float, float, float]
    confidence: float
    tokens: list[OCRToken] = field(default_factory=list)
    reading_order: int = 0


def split_columns(tokens: list[OCRToken], min_gap_ratio: float = 0.05) -> list[list[OCRToken]]:
    """Column split via gaps between the tokens' x-intervals.

    A new column starts when the horizontal gap since the previous column's
    rightmost token is at least ``min_gap_ratio`` of the total token span and
    at least 1.2x the median token height (so normal word spacing never
    splits a line into columns).
    """
    if len(tokens) <= 1:
        return [list(tokens)]
    x0 = min(t.bbox[0] for t in tokens)
    x1 = max(t.bbox[2] for t in tokens)
    width = x1 - x0
    if width <= 0:
        return [list(tokens)]
    heights = [t.bbox[3] - t.bbox[1] for t in tokens if t.bbox[3] > t.bbox[1]]
    min_gap = max(min_gap_ratio * width, 1.2 * float(np.median(heights)) if heights else 0.0)
    columns: list[list[OCRToken]] = []
    current: list[OCRToken] = []
    for token in sorted(tokens, key=lambda t: t.bbox[0]):
        if current:
            prev_right = max(p.bbox[2] for p in current)
            if token.bbox[0] - prev_right >= min_gap:
                columns.append(current)
                current = []
        current.append(token)
    if current:
        columns.append(current)
    return columns


def group_lines(tokens: list[OCRToken], overlap: float = 0.5) -> list[list[OCRToken]]:
    """Greedy line grouping within one column: a token joins a line when its
    vertical span overlaps the line's by >= ``overlap`` and it starts at or
    right of the line's leftmost token's left edge."""
    lines: list[list[OCRToken]] = []
    for token in sorted(tokens, key=lambda t: (t.bbox[1], t.bbox[0])):
        placed = False
        for line in lines:
            line_span = (min(t.bbox[1] for t in line), max(t.bbox[3] for t in line))
            tok_span = (token.bbox[1], token.bbox[3])
            if _vertical_overlap(line_span, tok_span) >= overlap:
                line.append(token)
                placed = True
                break
        if not placed:
            lines.append([token])
    for line in lines:
        line.sort(key=lambda t: t.bbox[0])
    return lines


def _vertical_overlap(a: tuple[float, float], b: tuple[float, float]) -> float:
    lo, hi = max(a[0], b[0]), min(a[1], b[1])
    span = min(a[1] - a[0], b[1] - b[0])
    if span <= 0:
        return 0.0
    return max(0.0, hi - lo) / span


def tokens_to_blocks(tokens: list[OCRToken]) -> list[TextBlock]:
    """Group tokens into columns, then lines; order columns left-to-right."""
    columns = split_columns(tokens)
    blocks: list[TextBlock] = []
    for column in columns:
        for line in group_lines(column):
            bbox = (
                min(t.bbox[0] for t in line),
                min(t.bbox[1] for t in line),
                max(t.bbox[2] for t in line),
                max(t.bbox[3] for t in line),
            )
            text = " ".join(t.text for t in line)
            conf = sum(t.confidence for t in line) / len(line)
            blocks.append(
                TextBlock(
                    text=text,
                    bbox=bbox,
                    confidence=conf,
                    tokens=list(line),
                    reading_order=len(blocks),
                )
            )
    return blocks


def blocks_to_text(blocks: list[TextBlock]) -> str:
    return "\n".join(b.text for b in sorted(blocks, key=lambda b: b.reading_order))
