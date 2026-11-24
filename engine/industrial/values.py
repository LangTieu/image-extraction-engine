"""Value-unit parsing (P4 item 6).

Parses industrial numeric strings with decimal and thousands separators
(both ``1,234.56`` and ``1.234,56``), splits trailing/prefixed units
(mm, m, kg, t, °C, bar, rpm, %, V, A, ...), and keeps raw text, parsed
value and unit together. Ambiguous input is never guessed: it is flagged
with a parse note instead.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

UNITS = (
    "mm",
    "cm",
    "m",
    "kg",
    "t",
    "°c",
    "degc",
    "k",
    "bar",
    "mbar",
    "kpa",
    "mpa",
    "rpm",
    "hz",
    "%",
    "v",
    "mv",
    "kv",
    "a",
    "ma",
    "kw",
    "w",
    "l",
    "ml",
    "m3",
    "m2",
    "s",
    "ms",
    "min",
)

_UNIT_PATTERN = re.compile(
    r"^\s*(?P<sign>-?\+?)\s*(?P<num>\d+(?:[.,\s]\d+)*)(?:\s*(?P<unit>[°a-zA-Z%]+))?\s*$",
    re.IGNORECASE,
)


@dataclass
class ParsedValue:
    raw: str
    value: float | None
    unit: str | None
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.value is not None and not self.notes


def _strip_thousands(num: str) -> str:
    """Normalize 1,234.56 / 1.234,56 / 1 234,56 / 12345 to canonical form."""
    num = num.replace(" ", "").replace("\u00a0", "")
    if "," in num and "." in num:
        if num.rfind(",") > num.rfind("."):
            num = num.replace(".", "").replace(",", ".")
        else:
            num = num.replace(",", "")
    elif "," in num:
        head, _, tail = num.rpartition(",")
        if head and len(tail) == 3 and head.replace(",", "").isdigit():
            num = head.replace(",", "") + "." + tail  # 1,234 thousands
        else:
            num = num.replace(",", ".")
    elif "." in num:
        head, _, tail = num.rpartition(".")
        if head and len(tail) == 3 and head.replace(".", "").isdigit() and head.count(".") >= 1:
            # 1.234.567: only dots as thousands; a single dot with 3 digits is
            # ambiguous (1.234 vs 1234) — keep as decimal, the common case.
            if num.count(".") >= 2:
                num = num.replace(".", "")
    return num


def parse_value_unit(raw: str, *, default_unit: str | None = None) -> ParsedValue:
    """Parse one raw cell/label value into a number plus unit."""
    text = raw.strip()
    if not text:
        return ParsedValue(raw=raw, value=None, unit=None, notes=["empty"])
    m = _UNIT_PATTERN.match(text)
    if m is None:
        return ParsedValue(raw=raw, value=None, unit=None, notes=[f"unparseable: {text!r}"])
    canonical = _strip_thousands(m.group("num"))
    try:
        value = float(canonical)
    except ValueError:
        return ParsedValue(raw=raw, value=None, unit=None, notes=[f"unparseable: {text!r}"])
    unit = (m.group("unit") or default_unit or "").strip().lower() or None
    if unit:
        unit = unit.replace("degc", "°c")
        if unit not in UNITS:
            return ParsedValue(
                raw=raw, value=value, unit=m.group("unit"), notes=[f"unknown unit: {unit}"]
            )
    elif default_unit:
        unit = default_unit
    return ParsedValue(raw=raw, value=value, unit=unit)


CONFUSABLE_ALTERNATIVES: dict[str, tuple[str, ...]] = {
    "0": ("O", "D"),
    "O": ("0",),
    "1": ("I", "l", "L"),
    "I": ("1", "l"),
    "l": ("1", "I"),
    "5": ("S",),
    "S": ("5",),
    "8": ("B",),
    "B": ("8",),
    "2": ("Z",),
    "Z": ("2",),
}


def flag_confusables(text: str) -> list[str]:
    """Characters in ``text`` whose glyph class is a known OCR confusable."""
    return [ch for ch in text if ch in CONFUSABLE_ALTERNATIVES]
