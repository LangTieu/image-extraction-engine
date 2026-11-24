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
from engine.validation.ambiguity import resolve_ambiguity
from engine.validation.normalize import normalize_field
from engine.validation.review import ReviewBackend, ReviewItem, ReviewThresholds


def _cell_threshold(
    thresholds: ReviewThresholds,
    table_name: str,
    column: str,
    profile_name: str | None,
) -> float:
    """Column-aware accept threshold; falls back to the table-wide config."""
    keys = [
        f"{profile_name}.{table_name}.{column}" if profile_name else None,
        f"{table_name}.{column}",
        column,
    ]
    for key in keys:
        if key and key in thresholds.per_field:
            return thresholds.per_field[key]
    return thresholds.threshold_for(table_name, profile_name)


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


def _profile_fields(profile_name: str | None) -> dict[str, Any]:
    """Field definitions declared by the named industrial profile ({} if none)."""
    if not profile_name:
        return {}
    try:
        from engine.industrial.profiles import bundled_profiles
    except Exception:  # pragma: no cover - profiles are optional at runtime
        return {}
    for prof in bundled_profiles():
        if getattr(prof, "name", None) == profile_name:
            return prof.fields
    return {}


def _normalize_stage(
    result_fields: list[Any],
    fields: dict[str, Any],
    profile_fields: dict[str, Any],
) -> list[rules_mod.Finding]:
    """Normalize string field values in place; ambiguous input is flagged."""
    findings: list[rules_mod.Finding] = []
    for f in result_fields:
        value = f.value
        if not isinstance(value, str) or not value.strip():
            continue
        fd = profile_fields.get(f.name)
        ftype = (getattr(fd, "type", None) if fd is not None else None) or "string"
        norm = normalize_field(value, type=ftype, unit=f.unit)
        if norm.notes:
            findings.append(
                rules_mod.Finding(
                    "NORMALIZE_AMBIGUOUS",
                    "warning",
                    "; ".join(norm.notes),
                    field_name=f.name,
                )
            )
            continue
        if norm.value is not None and norm.value != value:
            f.value = norm.value
            fields[f.name] = norm.value
    return findings


def _schema_stage(
    fields: dict[str, Any],
    profile_fields: dict[str, Any],
) -> list[rules_mod.Finding]:
    """Dynamic profile schema: type/format/min/max checks on the field dict."""
    if not profile_fields:
        return []
    from engine.validation.dynamic_schema import (
        build_model,
        contract_from_field_def,
        validate_fields,
    )

    contracts = [contract_from_field_def(fd) for fd in profile_fields.values()]
    model = build_model("profile_fields", contracts)
    outcome = validate_fields(fields, contracts, model=model)
    findings: list[rules_mod.Finding] = []
    for issue in outcome.issues:
        suffix = issue.id.removeprefix("FIELD_FORMAT_")
        field_name = next((c.name for c in contracts if c.name.upper() == suffix), None)
        findings.append(
            rules_mod.Finding(
                f"DYNAMIC_{issue.id}",
                issue.severity,
                issue.message,
                field_name=field_name,
            )
        )
    return findings


def _format_patterns(
    loaded: list[rules_mod.Rule],
    profile_fields: dict[str, Any],
) -> dict[str, list[str]]:
    """Format regexes per field/column name, from YAML rules + profile FieldDefs."""
    fmt: dict[str, list[str]] = {}
    for fd in profile_fields.values():
        regex = getattr(fd, "format_regex", None)
        if regex:
            fmt.setdefault(fd.name, []).append(regex)
    for rule in loaded:
        if rule.type != "format":
            continue
        pattern = rule.params.get("regex") or rule.params.get("pattern")
        if not pattern:
            continue
        names = list(rule.params.get("fields") or [])
        if rule.params.get("field"):
            names.append(rule.params["field"])
        if rule.params.get("column"):
            names.append(rule.params["column"])
        for name in names:
            fmt.setdefault(str(name), []).append(str(pattern))
    return fmt


def _ambiguity_stage(
    result: ExtractionResult,
    tables: dict[str, dict[str, Any]],
    fmt: dict[str, list[str]],
) -> tuple[list[rules_mod.Finding], dict[str, Any]]:
    """Confusable readings vs format rules: propose or flag, never guess."""
    findings: list[rules_mod.Finding] = []
    notes: dict[str, Any] = {}

    def record(name: str, finding: rules_mod.Finding, outcome: Any) -> None:
        findings.append(finding)
        notes[name] = {
            "raw": outcome.text,
            "status": outcome.status,
            "proposals": list(outcome.proposals),
            "reason": outcome.reason,
        }

    for f in result.fields:
        value = f.value
        if not isinstance(value, str):
            continue
        outcome = resolve_ambiguity(value, fmt.get(f.name, []))
        if outcome.status == "clean":
            continue
        f.proposals = list(outcome.proposals)
        if outcome.status == "proposed":
            record(
                f.name,
                rules_mod.Finding(
                    "AMBIGUITY_PROPOSED",
                    "warning",
                    f"possible readings {list(outcome.proposals)}; needs review",
                    field_name=f.name,
                ),
                outcome,
            )
        else:
            record(
                f.name,
                rules_mod.Finding(
                    "AMBIGUOUS_VALUE",
                    "error",
                    f"no safe reading ({outcome.reason})",
                    field_name=f.name,
                ),
                outcome,
            )
    for tname, t in tables.items():
        columns = t["columns"]
        for r_i, row in enumerate(t["rows"]):
            for c_i, cell in enumerate(row):
                if not isinstance(cell, str):
                    continue
                col = columns[c_i] if c_i < len(columns) else None
                patterns = fmt.get(col or "", [])
                if not patterns:
                    continue
                outcome = resolve_ambiguity(cell, patterns)
                if outcome.status == "clean":
                    continue
                table = t["table"]
                # Attach proposals to the live cell when one exists at this position.
                for c in table.cells:
                    if c.row_index == r_i and c.col_index == c_i:
                        c.proposals = list(outcome.proposals)
                if outcome.status == "proposed":
                    record(
                        f"{tname}.{col}[{r_i}]",
                        rules_mod.Finding(
                            "AMBIGUITY_PROPOSED",
                            "warning",
                            f"possible readings {list(outcome.proposals)}; needs review",
                            table_name=tname,
                            row_index=r_i,
                            col_index=c_i,
                        ),
                        outcome,
                    )
                else:
                    record(
                        f"{tname}.{col}[{r_i}]",
                        rules_mod.Finding(
                            "AMBIGUOUS_VALUE",
                            "error",
                            f"no safe reading ({outcome.reason})",
                            table_name=tname,
                            row_index=r_i,
                            col_index=c_i,
                        ),
                        outcome,
                    )
    return findings, notes


def _fallback_cell_label(
    tables: dict[str, dict[str, Any]], find: rules_mod.Finding
) -> str:
    """Column-name label for a cell finding (index fallback when unknown)."""
    name = find.table_name
    t = tables.get(name or "")
    if t and find.col_index is not None and 0 <= find.col_index < len(t["columns"]):
        return f"{name}.{t['columns'][find.col_index]}"
    return f"{name}.{find.col_index}"


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

    # 0) Profile context: field contracts (types, format regexes, ranges).
    profile_fields = _profile_fields(profile_name)

    # 1a) Normalization: clean/parse values in place, flag ambiguous input.
    findings = _normalize_stage(result.fields, fields, profile_fields)

    # 1b) Declarative rules from YAML (default + profile).
    loaded = rules_mod.load_rules(profile_name, rules_dir)
    findings += rules_mod.check_rules(loaded, fields, tables, field_units=field_units)

    # 1c) Dynamic profile schema (type/format/min-max on the field dict).
    findings += _schema_stage(fields, profile_fields)

    # 1d) Confusable readings: propose or flag, never guess.
    amb_findings, amb_notes = _ambiguity_stage(
        result, tables, _format_patterns(loaded, profile_fields)
    )
    findings += amb_findings

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
            # Only errors count as a rule failure for the big penalty; warnings
            # already decay via n_warnings (a warning-only field keeps a real
            # reason for any confidence drop in its validation_results).
            rule_ok=(n_err == 0) if n_err else None,
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
                # Errors only: see the field-level note above.
                rule_ok=(n_err == 0) if n_err else None,
                n_errors=n_err,
                n_warnings=n_warn,
            )
            cell_conf[(tname, cell.row_index, cell.col_index)] = conf
            col = (
                t.columns[cell.col_index]
                if cell.col_index < len(t.columns)
                else cell.col_index
            )
            cell.needs_review = bool(n_err) or conf < _cell_threshold(
                thresholds, tname, str(col), profile_name
            )
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
            "proposals": list(f.proposals or []),
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
            "proposals": list(c.proposals or []),
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
                        "field_name": _fallback_cell_label(tables, find),
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
        "ambiguity": amb_notes,
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
