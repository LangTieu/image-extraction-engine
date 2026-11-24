"""Anomaly flags (P5 item 6).

Statistical and structural checks beyond per-field rules: column
distribution outliers (median + MAD), duplicate rows, unit mismatches
against the profile, impossible values, and vision-vs-OCR contradictions
when a vision assist hook recorded independent readings.
"""

from __future__ import annotations

from typing import Any

from engine.validation.rules import Finding


def _median(xs: list[float]) -> float:
    xs = sorted(xs)
    n = len(xs)
    mid = n // 2
    return xs[mid] if n % 2 else (xs[mid - 1] + xs[mid]) / 2


def _mad(xs: list[float], med: float) -> float:
    return _median([abs(x - med) for x in xs])


def detect_column_outliers(
    tables: dict[str, dict[str, Any]], *, z_threshold: float = 3.5
) -> list[Finding]:
    """Median + MAD outliers per numeric column (needs >= 4 values)."""
    findings: list[Finding] = []
    for tname, table in tables.items():
        cols = table["columns"]
        for ci, col in enumerate(cols):
            values: list[tuple[int, float]] = []
            for ri, row in enumerate(table["rows"]):
                v = row[ci] if ci < len(row) else None
                if v is None:
                    continue
                try:
                    values.append((ri, float(str(v).strip())))
                except ValueError:
                    continue
            if len(values) < 4:
                continue
            xs = [v for _, v in values]
            med = _median(xs)
            mad = _mad(xs, med)
            if mad == 0:
                continue  # all identical; nothing to say statistically
            scale = 1.4826 * mad
            for ri, v in values:
                if abs(v - med) / scale > z_threshold:
                    findings.append(
                        Finding(
                            "ANOMALY_COLUMN_OUTLIER",
                            "warning",
                            f"{col}={v:g} is a statistical outlier vs column median {med:g}",
                            table_name=tname,
                            row_index=ri,
                            col_index=ci,
                        )
                    )
    return findings


def detect_duplicate_rows(tables: dict[str, dict[str, Any]]) -> list[Finding]:
    findings: list[Finding] = []
    for tname, table in tables.items():
        seen: dict[tuple, int] = {}
        for ri, row in enumerate(table["rows"]):
            key = tuple(str(v).strip().upper() if v is not None else "" for v in row)
            if key in seen and any(key):
                findings.append(
                    Finding(
                        "ANOMALY_DUPLICATE_ROW",
                        "warning",
                        f"row {ri} duplicates row {seen[key]}",
                        table_name=tname,
                        row_index=ri,
                    )
                )
            else:
                seen[key] = ri
    return findings


def detect_unit_mismatches(
    fields: dict[str, Any],
    field_units: dict[str, str | None],
    profile_units: dict[str, str | None],
) -> list[Finding]:
    """Extracted unit differs from the profile's declared unit for the field."""
    findings: list[Finding] = []
    for name, unit in field_units.items():
        expected = (profile_units.get(name) or "").strip().lower()
        actual = (unit or "").strip().lower()
        if expected and actual and actual != expected:
            findings.append(
                Finding(
                    "ANOMALY_UNIT_MISMATCH",
                    "warning",
                    f"{name}: extracted unit {actual!r} differs from profile unit {expected!r}",
                    field_name=name,
                )
            )
    return findings


def detect_impossible_values(
    fields: dict[str, Any], profile_ranges: dict[str, tuple[float, float]]
) -> list[Finding]:
    """Values that cannot possibly be right (not numeric where numeric is required)."""
    findings: list[Finding] = []
    for name, (lo, hi) in profile_ranges.items():
        value = fields.get(name)
        if value is None:
            continue
        try:
            num = float(str(value).strip())
        except ValueError:
            findings.append(
                Finding(
                    "ANOMALY_IMPOSSIBLE_VALUE",
                    "error",
                    f"{name}={value!r} is not numeric for a numeric field",
                    field_name=name,
                )
            )
            continue
        if num < lo or num > hi:
            findings.append(
                Finding(
                    "ANOMALY_IMPOSSIBLE_VALUE",
                    "error",
                    f"{name}={num:g} is outside the physically possible range [{lo}, {hi}]",
                    field_name=name,
                )
            )
    return findings


def detect_vision_contradictions(
    fields: dict[str, Any],
    vision_fields: dict[str, Any] | None,
) -> list[Finding]:
    """A vision-assist reading that disagrees with the OCR pipeline reading."""
    findings: list[Finding] = []
    if not vision_fields:
        return findings
    for name, vision_value in vision_fields.items():
        ocr_value = fields.get(name)
        if ocr_value is None or vision_value is None:
            continue
        if str(ocr_value).strip().upper() != str(vision_value).strip().upper():
            findings.append(
                Finding(
                    "ANOMALY_VISION_CONTRADICTION",
                    "warning",
                    f"{name}: OCR reads {ocr_value!r} but vision assist reads {vision_value!r}",
                    field_name=name,
                )
            )
    return findings


def detect_anomalies(
    fields: dict[str, Any],
    tables: dict[str, dict[str, Any]],
    *,
    field_units: dict[str, str | None] | None = None,
    profile_units: dict[str, str | None] | None = None,
    profile_ranges: dict[str, tuple[float, float]] | None = None,
    vision_fields: dict[str, Any] | None = None,
) -> list[Finding]:
    findings: list[Finding] = []
    findings += detect_column_outliers(tables)
    findings += detect_duplicate_rows(tables)
    if field_units and profile_units:
        findings += detect_unit_mismatches(fields, field_units, profile_units)
    if profile_ranges:
        findings += detect_impossible_values(fields, profile_ranges)
    findings += detect_vision_contradictions(fields, vision_fields)
    return findings
