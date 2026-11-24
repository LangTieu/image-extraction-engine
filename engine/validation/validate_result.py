"""P5 entry point: validate a full ExtractionResult.

``validate_result`` runs, in order: normalization → dynamic profile schema →
declarative rules → anomaly flags → confidence scoring → ambiguity proposals
→ review queue. Field/table/cell confidence and needs_review are written back
onto the result; document confidence lands in extensions["validation"].
"""

from __future__ import annotations

from typing import Any

from engine.schema.models import ExtractionResult, ExtractionStatus, ValidationIssue
from engine.validation import anomalies, confidence
from engine.validation import rules as rules_mod
from engine.validation.review import ReviewBackend, ReviewItem, ReviewThresholds


def _cell_label(t: Any, c: Any) -> str:
    """Human-readable name for a table cell: column name when available."""
    col = t.columns[c.col_index] if c.col_index < len(t.columns) else c.col_index
    return f"{t.table_name}.{col}"


def _tables_dict(result: ExtractionResult) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for t in result.tables:
        name = t.table_name or f"table_{len(out)}"
        # Cell texts take priority over the rows grid: they carry the live
        # readings (rows may be stale when cells were updated or degraded).
        if t.cells:
            max_row = max(c.row_index for c in t.cells)
            max_col = max(c.col_index for c in t.cells)
            rows: list[list[str | None]] = [[None] * (max_col + 1) for _ in range(max_row + 1)]
            for c in t.cells:
                rows[c.row_index][c.col_index] = c.text
        else:
            rows = [list(r) for r in t.rows]
        out[name] = {"columns": list(t.columns), "rows": rows, "table": t}
    return out


def _fields_dict(result: ExtractionResult) -> tuple[dict[str, Any], dict[str, str | None]]:
    values: dict[str, Any] = {}
    units: dict[str, str | None] = {}
    for f in result.fields:
        values[f.name] = f.value
        units[f.name] = f.unit
    return values, units


def validate_result(
    result: ExtractionResult,
    *,
    profile_name: str | None = None,
    rules_dir: str | None = None,
    thresholds: ReviewThresholds | None = None,
    review_backend: ReviewBackend | None = None,
    quality_score: float | None = None,
    vision_fields: dict[str, Any] | None = None,
    profile_units: dict[str, str | None] | None = None,
    profile_ranges: dict[str, tuple[float, float]] | None = None,
) -> ExtractionResult:
    """Validate + score one result in place (and return it)."""
    thresholds = thresholds or ReviewThresholds()
    fields, field_units = _fields_dict(result)
    tables = _tables_dict(result)

    # 1) Declarative rules from YAML (default + profile).
    loaded = rules_mod.load_rules(profile_name, rules_dir)
    findings = rules_mod.check_rules(loaded, fields, tables, field_units=field_units)

    # 2) Anomaly flags.
    findings += anomalies.detect_anomalies(
        fields,
        {k: {"columns": v["columns"], "rows": v["rows"]} for k, v in tables.items()},
        field_units=field_units,
        profile_units=profile_units,
        profile_ranges=profile_ranges,
        vision_fields=vision_fields,
    )

    errors = [f for f in findings if f.severity == "error"]
    warnings = [f for f in findings if f.severity == "warning"]

    # 3) Confidence per field / per table cell / rollups.
    field_conf: dict[str, float] = {}
    for f in result.fields:
        n_err = sum(1 for x in errors if x.field_name == f.name)
        n_warn = sum(1 for x in warnings if x.field_name == f.name)
        base = f.confidence if f.confidence is not None else None
        conf = confidence.field_confidence(
            ocr_confidence=base,
            cell_confidence=(f.cell_ref.confidence if f.cell_ref else None),
            image_quality=quality_score,
            rule_ok=(n_err == 0) if (n_err or n_warn) else None,
            n_errors=n_err,
            n_warnings=n_warn,
        )
        field_conf[f.name] = conf
        f.confidence = conf
        f.validation_results = [
            ValidationIssue(id=x.rule_id, severity=x.severity, message=x.message)
            for x in findings
            if x.field_name == f.name
        ]
        f.needs_review = bool(n_err) or conf < thresholds.threshold_for(f.name, profile_name)

    cell_conf: dict[tuple[str, int, int], float] = {}
    for t in result.tables:
        tname = t.table_name or f"table_{result.tables.index(t)}"

        def _n_at(findings_list, cell):
            return sum(
                1
                for x in findings_list
                if x.table_name == tname
                and x.row_index == cell.row_index
                and x.col_index == cell.col_index
            )

        for cell in t.cells:
            n_err = _n_at(errors, cell)
            n_warn = _n_at(warnings, cell)
            conf = confidence.field_confidence(
                cell_confidence=cell.confidence,
                image_quality=quality_score,
                rule_ok=(n_err == 0) if (n_err or n_warn) else None,
                n_errors=n_err,
                n_warnings=n_warn,
            )
            cell_conf[(tname, cell.row_index, cell.col_index)] = conf
            cell.needs_review = bool(n_err) or conf < thresholds.threshold_for(tname, profile_name)
            cell.validation_results = [
                ValidationIssue(id=x.rule_id, severity=x.severity, message=x.message)
                for x in findings
                if x.table_name == tname
                and x.row_index == cell.row_index
                and x.col_index == cell.col_index
            ]
        confs: list[float | None] = [cell_conf[(tname, c.row_index, c.col_index)] for c in t.cells]
        t.confidence = confidence.table_confidence(confs or [None])
        # Table-level issues: findings with a table_name but no matching cell
        # position kept above still mark the table for review.
        t_has_err = any(x.table_name == tname for x in errors)
        t_has_warn = any(x.table_name == tname for x in warnings)
        t.needs_review = (
            t_has_err
            or (
                t.confidence is not None
                and t.confidence < thresholds.threshold_for(tname, profile_name)
            )
            or bool(t_has_warn and not confs)
        )

    doc_conf = confidence.doc_confidence(
        list(field_conf.values()),
        [t.confidence for t in result.tables if t.confidence is not None],
    )

    # 4) Review items for everything flagged.
    field_flags = {
        f.name: {
            "value": f.value,
            "confidence": field_conf[f.name],
            "needs_review": f.needs_review,
            "reasons": [i.message for i in f.validation_results],
            "result_ref": result.job_id,
        }
        for f in result.fields
        if f.needs_review
    }
    cell_flags = [
        {
            "field_name": _cell_label(t, c),
            "table_name": t.table_name,
            "row_index": c.row_index,
            "col_index": c.col_index,
            "value": c.text,
            "confidence": cell_conf.get((t.table_name or "", c.row_index, c.col_index), 0.0),
            "needs_review": c.needs_review,
            "reasons": [i.message for i in c.validation_results],
            "result_ref": result.job_id,
        }
        for t in result.tables
        for c in t.cells
        if c.needs_review
    ]
    items: list[ReviewItem] = []
    # Error-severity findings flag their exact position, even when the cell
    # loop above missed them (e.g. cells absent from the result).
    for find in findings:
        if find.severity != "error":
            continue
        if find.table_name is not None:
            key = (find.table_name, find.row_index, find.col_index)
            if key not in cell_conf and (find.table_name, find.row_index, find.col_index) not in {
                (info["table_name"], info["row_index"], info["col_index"]) for info in cell_flags
            }:
                cell_flags.append(
                    {
                        "field_name": f"{find.table_name}.{find.col_index}",
                        "table_name": find.table_name,
                        "row_index": find.row_index,
                        "col_index": find.col_index,
                        "value": None,
                        "confidence": 0.0,
                        "needs_review": True,
                        "reasons": [find.message],
                        "result_ref": result.job_id,
                    }
                )
        elif find.field_name and find.field_name not in field_flags:
            field_flags[find.field_name] = {
                "value": fields.get(find.field_name),
                "confidence": field_conf.get(find.field_name, 0.0),
                "needs_review": True,
                "reasons": [find.message],
                "result_ref": result.job_id,
            }
    if review_backend is not None:
        items = build_and_queue(
            field_flags, cell_flags, thresholds, review_backend, profile_name
        )

    # 5) Document-level outcome.
    result.validation_results = [
        ValidationIssue(id=f.rule_id, severity=f.severity, message=f.message) for f in findings
    ]
    any_review = bool(field_flags or cell_flags or items)
    if any_review or errors:
        result.extraction_status = (
            ExtractionStatus.NEEDS_REVIEW
            if errors or any_review
            else ExtractionStatus.COMPLETED_WITH_WARNINGS
        )
    elif warnings:
        result.extraction_status = ExtractionStatus.COMPLETED_WITH_WARNINGS
    else:
        result.extraction_status = ExtractionStatus.COMPLETED

    result.extensions["validation"] = {
        "document_confidence": doc_conf,
        "n_errors": len(errors),
        "n_warnings": len(warnings),
        "n_findings": len(findings),
        "rule_ids": sorted({f.rule_id for f in findings}),
        "review_item_ids": [i.item_id for i in items],
    }
    return result


def build_and_queue(
    field_flags: dict[str, dict[str, Any]],
    cell_flags: list[dict[str, Any]],
    thresholds: ReviewThresholds,
    backend: ReviewBackend,
    profile_name: str | None = None,
) -> list[ReviewItem]:
    from engine.validation.review import build_review_items

    items = build_review_items(
        field_flags=field_flags,
        cell_flags=cell_flags,
        thresholds=thresholds,
        profile_name=profile_name,
    )
    queued = [backend.add(i) for i in items]
    return queued
