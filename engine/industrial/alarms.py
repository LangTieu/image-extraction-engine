"""Alarm and status extraction (P4 item 7).

Recognizes alarm rows (timestamp + code + message), normalizes severity
from message keywords and banner colour, and reads status indicators as
(colour, state) pairs. Nothing is inferred when the timestamp or code is
unreadable — the row is flagged for review instead.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np

from engine.ocr.base import OCRToken
from engine.schema.models import Provenance

TIMESTAMP_RE = re.compile(
    r"(\d{4}[-/]\d{2}[-/]\d{2}[ T]?\d{1,2}:\d{2}(?::\d{2})?)"
    r"|(\d{1,2}:\d{2}(?::\d{2})?)"
)
CODE_RE = re.compile(r"\b([A-Z]{1,4}[-_ ]?\d{2,6})\b")

SEVERITY_KEYWORDS = {
    "critical": ("crit", "emergency", "fault", "lỗi nghiêm", "trip"),
    "warning": ("warn", "alarm", "cảnh báo", "high", "low"),
    "info": ("info", "notice", "thông báo"),
}


@dataclass
class AlarmEntry:
    timestamp: str | None
    code: str | None
    message: str
    severity: str | None  # critical | warning | info | None (unknown)
    color: str | None = None
    flags: list[str] = field(default_factory=list)
    # Position of the alarm banner in ORIGINAL-image coordinates. None when
    # the caller had no transform log (raw working-space crop only) — see
    # IndustrialVision._extract_alarms.
    prov: list[Provenance] | None = None


@dataclass
class StatusIndicator:
    color: str
    state: str | None  # "on" | "off" | None when brightness is inconclusive
    bbox: tuple[float, float, float, float]


def parse_alarm_row(
    tokens: list[OCRToken],
    *,
    banner_color: str | None = None,
) -> AlarmEntry | None:
    """Turn one banner/row of tokens into an AlarmEntry, or None if not an alarm."""
    line = " ".join(t.text for t in tokens)
    if not line.strip():
        return None
    ts = TIMESTAMP_RE.search(line)
    code = CODE_RE.search(line)
    if ts is None and code is None:
        return None
    flags: list[str] = []
    if ts is None:
        flags.append("timestamp_unreadable")
    if code is None:
        flags.append("code_unreadable")
    severity = None
    lowered = line.lower()
    for level, words in SEVERITY_KEYWORDS.items():
        if any(w in lowered for w in words):
            severity = level
            break
    if severity is None and banner_color is not None:
        severity = {"red": "critical", "red2": "critical", "yellow": "warning"}.get(banner_color)
    return AlarmEntry(
        timestamp=ts.group(0) if ts else None,
        code=code.group(1) if code else None,
        message=line.strip(),
        severity=severity,
        color=banner_color,
        flags=flags,
    )


def indicator_state(image: np.ndarray, bbox: tuple[float, float, float, float]) -> str | None:
    """Read one indicator region as on/off by mean brightness of its core."""
    x0, y0, x1, y1 = (int(v) for v in bbox)
    crop = image[y0:y1, x0:x1]
    if crop.size == 0:
        return None
    gray = crop.astype(float)
    if gray.ndim > 2:  # any channel count: fold colour channels to gray
        gray = gray.mean(axis=-1)
    r0, r1 = gray.shape[0] // 4, 3 * gray.shape[0] // 4
    c0, c1 = gray.shape[1] // 4, 3 * gray.shape[1] // 4
    core = gray[r0:r1, c0:c1]
    if core.size == 0:
        return None
    if core.mean() > 140:
        return "on"
    if core.mean() < 70:
        return "off"
    return None  # ambiguous: never guess
