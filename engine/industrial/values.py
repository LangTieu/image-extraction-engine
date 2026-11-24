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
    r"^\s*(?P<sign>-?\+?)\s*(?P<num>\d+(?:[.,\s]\d+)*)"
    r"(?:\s*(?P<unit>[°a-zA-Z%]+(?:\s*/\s*[°a-zA-Z%]+)*(?:\s*\^?\d+)?))?\s*$",
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


def _strip_thousands(num: str) -> tuple[str, str | None]:
    """Normalize 1,234.56 / 1.234,56 / 1 234,56 / 12345 to canonical form.

    Returns the canonical string plus an ambiguity note (None when the
    grouping is unambiguous).
    """
    num = num.replace(" ", "").replace("\u00a0", "")
    if "," in num and "." in num:
        if num.rfind(",") > num.rfind("."):
            num = num.replace(".", "").replace(",", ".")
        else:
            num = num.replace(",", "")
    elif "," in num:
        if num.count(",") > 1:
            # 1,234,567: repeated commas are thousands grouping only.
            num = num.replace(",", "")
        else:
            head, _, tail = num.rpartition(",")
            if head.isdigit() and len(tail) == 3:
                # 1,234 thousands grouping: the separator is REMOVED, never
                # turned into a decimal point (that would read 1000x small).
                num = head + tail
            elif head.isdigit() and 1 <= len(tail) <= 2:
                num = head + "." + tail  # 12,5 decimal — unambiguous
            else:
                # e.g. 12,3456: could be decimal or bad grouping — flag it.
                return num, f"ambiguous number: {num!r}"
    elif "." in num:
        head, _, tail = num.rpartition(".")
        if head and len(tail) == 3 and head.replace(".", "").isdigit() and head.count(".") >= 1:
            # 1.234.567: only dots as thousands; a single dot with 3 digits is
            # ambiguous (1.234 vs 1234) — keep as decimal, the common case.
            if num.count(".") >= 2:
                num = num.replace(".", "")
    return num, None


def parse_value_unit(raw: str, *, default_unit: str | None = None) -> ParsedValue:
    """Parse one raw cell/label value into a number plus unit."""
    text = raw.strip()
    if not text:
        return ParsedValue(raw=raw, value=None, unit=None, notes=["empty"])
    m = _UNIT_PATTERN.match(text)
    if m is None:
        return ParsedValue(raw=raw, value=None, unit=None, notes=[f"unparseable: {text!r}"])
    canonical, note = _strip_thousands(m.group("num"))
    notes: list[str] = [note] if note else []
    try:
        value = float(canonical)
    except ValueError:
        return ParsedValue(raw=raw, value=None, unit=None, notes=[f"unparseable: {text!r}"])
    unit = m.group("unit")
    if unit:
        # Compound units: "kg/m2", "m/min", "kg/m^2" -> "kg/m2".
        unit = unit.replace(" ", "").replace("^", "").lower()
        parts = [p for p in unit.split("/") if p]
        known = unit in UNITS or (len(parts) > 1 and all(p in UNITS for p in parts))
        if not known:
            return ParsedValue(
                raw=raw, value=value, unit=m.group("unit"), notes=[f"unknown unit: {unit}"]
            )
    else:
        unit = default_unit.lower().replace("degc", "°c") if default_unit else None
        if unit:
            notes.append(f"unit defaulted to {unit}")
    return ParsedValue(raw=raw, value=value, unit=unit, notes=notes)


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


def disambiguate(text: str, alternatives: list[str], format_regex: str) -> str:
    """Pick the OCR reading that matches the field's format regex.

    Ties or no-match fall back to the primary reading.
    """
    import re as _re

    def score(candidate: str) -> tuple[int, int]:
        matched = 1 if _re.fullmatch(format_regex, candidate) else 0
        # tiebreak: IDs like H00002 are letters followed by a digit run;
        # prefer candidates whose tail after the last letter is all digits.
        tail = candidate.rstrip("0123456789")
        clean_tail = len(candidate) - len(tail) if tail else 0
        return (matched, clean_tail)

    best = max([text, *alternatives], key=score)
    return best if score(best)[0] else text


def flag_confusables(text: str) -> list[str]:
    """Characters in ``text`` whose glyph class is a known OCR confusable."""
    return [ch for ch in text if ch in CONFUSABLE_ALTERNATIVES]
