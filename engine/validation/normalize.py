"""Normalization layer (P5 item 2).

Turns raw OCR text into clean typed values. Factory-specific formats
(decimal separator, date order) come from the locale configuration so a
new factory needs no code change. Raw text is always kept next to the
normalized value; ambiguous input is flagged, never guessed.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime

_WHITESPACE = re.compile(r"\s+")
_INTEGER = re.compile(r"^[+-]?\d+$")

# Length/weight families: keep the original unit, expose the SI-canonical one.
_UNIT_TO_CANONICAL: dict[str, tuple[str, float]] = {
    "mm": ("m", 0.001),
    "cm": ("m", 0.01),
    "m": ("m", 1.0),
    "g": ("kg", 0.001),
    "kg": ("kg", 1.0),
    "t": ("kg", 1000.0),
    "ton": ("kg", 1000.0),
}

_DATE_SEPARATORS = re.compile(r"[.\-/]")


@dataclass
class LocaleConfig:
    """Per-factory format conventions (P5 item 8: configurable per profile)."""

    decimal_separator: str = "."  # "." for en, "," for vi/de
    thousands_separator: str = ","  # "," for en, "." for vi/de
    date_order: str = "DMY"  # "DMY" | "MDY" | "YMD"

    @classmethod
    def from_name(cls, name: str | None) -> LocaleConfig:
        if name in ("vi", "de", "vn"):
            return cls(decimal_separator=",", thousands_separator=".")
        return cls()


@dataclass
class NormalizedValue:
    raw_text: str
    value: str | float | int | None = None  # normalized in the ORIGINAL unit/format
    unit: str | None = None  # original unit, kept verbatim
    canonical_unit: str | None = None
    canonical_value: float | None = None  # value converted to canonical_unit
    iso_date: str | None = None  # YYYY-MM-DD for dates
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.notes


def normalize_text(text: str) -> str:
    """Unicode NFC + whitespace collapse + strip."""
    return _WHITESPACE.sub(" ", unicodedata.normalize("NFC", text)).strip()


def normalize_number(text: str, locale: LocaleConfig | None = None) -> NormalizedValue:
    """Parse a number honoring the locale's decimal/thousands separators.

    Ambiguous groupings (e.g. ``1.234`` under a dot-thousands locale with no
    other signal) stay ambiguous: the value parses, but a note is attached.
    """
    loc = locale or LocaleConfig()
    raw = normalize_text(text)
    if not raw:
        return NormalizedValue(raw_text=text, notes=["empty"])
    dec, thou = loc.decimal_separator, loc.thousands_separator
    body = raw.replace(" ", "").replace("\u00a0", "")
    sign = ""
    if body[:1] in "+-":
        sign, body = body[0], body[1:]
    if thou in body and dec in body:
        # Both present: whichever comes last is the decimal separator.
        if body.rfind(thou) > body.rfind(dec):
            dec, thou = thou, dec
        body = body.replace(thou, "").replace(dec, ".")
    elif thou in body:
        groups = body.split(thou)
        lens = {len(g) for g in groups[1:]}
        if _INTEGER.fullmatch(groups[0]) and len(lens) == 1 and lens.pop() in (2, 3):
            body = body.replace(thou, "")  # consistent thousands grouping
        else:
            return NormalizedValue(
                raw_text=text, value=None, notes=[f"ambiguous grouping: {raw!r}"]
            )
    elif dec in body:
        body = body.replace(dec, ".")
    candidate = f"{sign}{body}"
    try:
        value = float(candidate)
    except ValueError:
        return NormalizedValue(raw_text=text, value=None, notes=[f"unparseable: {raw!r}"])
    if _INTEGER.fullmatch(candidate):
        return NormalizedValue(raw_text=text, value=int(candidate))
    return NormalizedValue(raw_text=text, value=value)


def normalize_date(text: str, locale: LocaleConfig | None = None) -> NormalizedValue:
    """Parse common date formats to ISO YYYY-MM-DD; never guesses the order."""
    loc = locale or LocaleConfig()
    raw = normalize_text(text)
    parts = _DATE_SEPARATORS.split(raw)
    if len(parts) != len(loc.date_order) or not all(p.isdigit() for p in parts):
        return NormalizedValue(raw_text=text, notes=[f"unparseable date: {raw!r}"])
    try:
        if "Y" not in loc.date_order:
            return NormalizedValue(raw_text=text, notes=[f"unparseable date: {raw!r}"])
        # A four-digit component is always the year; the remaining two follow
        # the locale's order for the other letters.
        four_digit = [i for i, p in enumerate(parts) if len(p) == 4]
        if len(four_digit) == 1:
            y_i = four_digit[0]
            others = [i for i in range(len(parts)) if i != y_i]
            # A leading year is always big-endian (year month day, as in ISO);
            # otherwise the non-year components keep the locale's order.
            letters = (
                ["M", "D"] if y_i == 0 else [c for c in loc.date_order if c != "Y"]
            )
            pos = dict(zip(letters, others))
            y, m, d = int(parts[y_i]), int(parts[pos["M"]]), int(parts[pos["D"]])
        else:
            keys = {"Y": 0, "M": 1, "D": 2}
            order_idx = [keys[c] for c in loc.date_order]
            y, m, d = (int(parts[i]) for i in order_idx)
        iso = datetime(y, m, d)
    except ValueError:
        return NormalizedValue(raw_text=text, notes=[f"invalid date: {raw!r}"])
    return NormalizedValue(raw_text=text, value=raw, iso_date=iso.strftime("%Y-%m-%d"))


def canonical_quantity(value: float, unit: str | None) -> tuple[str | None, float | None]:
    """Map a value+unit to the SI-canonical unit (mm→m, t→kg, ...).

    The original unit is kept on NormalizedValue.unit; this only adds the
    canonical view used by cross-field rules.
    """
    if unit is None:
        return None, None
    entry = _UNIT_TO_CANONICAL.get(unit.strip().lower())
    if entry is None:
        return None, None
    canon_unit, factor = entry
    return canon_unit, value * factor


def normalize_field(
    raw_text: str,
    *,
    type: str = "string",  # noqa: A002 - mirrors FieldDef.type
    unit: str | None = None,
    locale: LocaleConfig | None = None,
) -> NormalizedValue:
    """Normalize one field value according to its declared type."""
    loc = locale or LocaleConfig()
    if type == "date":
        return normalize_date(raw_text, loc)
    if type in ("number", "integer"):
        norm = normalize_number(raw_text, loc)
        if norm.ok and norm.value is not None and not isinstance(norm.value, int):
            if type == "integer":
                if float(norm.value).is_integer():
                    norm.value = int(norm.value)
                else:
                    norm.notes.append("not an integer")
        if norm.ok and norm.value is not None:
            norm.canonical_unit, norm.canonical_value = canonical_quantity(
                float(norm.value), unit or norm.unit
            )
        return norm
    text = normalize_text(raw_text)
    return NormalizedValue(raw_text=raw_text, value=text or None)
