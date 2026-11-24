"""Industrial field dictionary: coil fields with types, units, formats, ranges.

Factory-specific values (regex formats, plausible ranges, column aliases) are
marked configurable and are meant to be overridden per factory profile in
later phases (P4). The definitions here are the engine defaults.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class IndustrialField:
    name: str
    type: str  # "string" | "id" | "number" | "integer"
    unit: str | None
    format_regex: str | None  # placeholder pattern; refine per factory profile
    min_value: float | None
    max_value: float | None
    description: str
    configurable: bool = True  # factory profiles may override format/ranges


DEFAULT_FIELDS: dict[str, IndustrialField] = {
    f.name: f
    for f in [
        IndustrialField(
            "ZONE",
            "string",
            None,
            r"^[A-Z]{1,4}\d{0,3}$",
            None,
            None,
            "Production zone code, e.g. 'ZA', 'LINE1'.",
        ),
        IndustrialField(
            "HOT_COIL_NO",
            "id",
            None,
            r"^[A-Z0-9\-]{6,20}$",
            None,
            None,
            "Hot coil identifier; compact alphanumeric, often no spaces.",
        ),
        IndustrialField(
            "COLD_COIL_NO",
            "id",
            None,
            r"^[A-Z0-9\-]{6,20}$",
            None,
            None,
            "Cold coil identifier after processing.",
        ),
        IndustrialField(
            "THICK",
            "number",
            "mm",
            r"^\d{1,2}\.\d{1,3}$",
            0.05,
            500.0,
            "Coil thickness in millimetres (2-3 decimals typical).",
        ),
        IndustrialField(
            "WIDTH",
            "number",
            "mm",
            r"^\d{3,5}(\.\d{1,2})?$",
            10.0,
            5000.0,
            "Coil width in millimetres.",
        ),
        IndustrialField(
            "WEIGHT",
            "number",
            "kg",
            r"^\d{3,7}(\.\d{1,2})?$",
            0.1,
            100_000.0,
            "Coil weight in kilograms (tons shown as kg or 'T' per profile).",
        ),
        IndustrialField(
            "LENGTH",
            "number",
            "m",
            r"^\d{2,7}(\.\d{1,2})?$",
            1.0,
            100_000.0,
            "Coil length in metres.",
        ),
        IndustrialField(
            "PRODUCT_CODE",
            "string",
            None,
            r"^[A-Z0-9\-\.x]{3,30}$",
            None,
            None,
            "Product/grade code, e.g. 'SPHC-1.2x1250'.",
        ),
    ]
}


def get_field(name: str) -> IndustrialField:
    return DEFAULT_FIELDS[name]


def validate_value(name: str, value: str | int | float) -> list[str]:
    """Lightweight rule-based check used by validation later.

    Returns a list of human-readable problems; empty list means the value
    matches the dictionary's format and range.
    """
    problems: list[str] = []
    spec = DEFAULT_FIELDS.get(name)
    if spec is None:
        return [f"unknown field: {name}"]
    text = str(value)
    if spec.format_regex is not None:
        import re

        if re.fullmatch(spec.format_regex, text) is None:
            problems.append(f"{name}: value {text!r} does not match format {spec.format_regex}")
    if spec.min_value is not None or spec.max_value is not None:
        try:
            number = float(text)
        except ValueError:
            problems.append(f"{name}: value {text!r} is not numeric but field has a range")
            return problems
        if spec.min_value is not None and number < spec.min_value:
            problems.append(f"{name}: {number} below plausible minimum {spec.min_value}")
        if spec.max_value is not None and number > spec.max_value:
            problems.append(f"{name}: {number} above plausible maximum {spec.max_value}")
    return problems
