"""Declarative validation rules (P5 item 4).

Rules live in YAML files (``engine/validation/rules/``): one ``default.yaml``
plus optional per-profile files named ``<profile>.yaml``. A rule has an ID,
a severity (error/warning/info), a human message and a typed checker.
Factories change rules and thresholds by editing YAML — no code change.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any, Literal

import yaml

Severity = Literal["error", "warning", "info"]

RULE_TYPES = ("range", "format", "cross_field", "uniqueness", "row_count", "unit_match")


@dataclass(frozen=True)
class Rule:
    id: str
    type: str
    severity: Severity = "error"  # error | warning | info
    message: str = ""
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Finding:
    """One rule violation, tied to the field/table cell it concerns."""

    rule_id: str
    severity: Severity
    message: str
    field_name: str | None = None
    table_name: str | None = None
    row_index: int | None = None
    col_index: int | None = None


def load_rules(
    profile_name: str | None = None,
    directory: str | Path | None = None,
) -> list[Rule]:
    """Load default.yaml plus <profile>.yaml; a profile rule replaces a
    default rule with the same ID, so thresholds can be tightened per factory."""
    root = (
        Path(directory)
        if directory is not None
        else resources.files("engine.validation").joinpath("rules")
    )
    root = Path(str(root))
    if not root.is_dir():
        return []
    files = [root / "default.yaml"]
    if profile_name:
        for ext in (".yaml", ".yml"):
            candidate = root / f"{profile_name}{ext}"
            if candidate.exists():
                files.append(candidate)
                break
    rules: dict[str, Rule] = {}
    for path in files:
        if not path.exists():
            continue
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for item in data.get("rules") or []:
            rule = Rule(
                id=str(item["id"]),
                type=item["type"],
                severity=item.get("severity", "error"),
                message=item.get("message", ""),
                params=dict(item.get("params") or {}),
            )
            if rule.type not in RULE_TYPES:
                raise ValueError(f"{path}: unknown rule type {rule.type!r} in {rule.id}")
            rules[rule.id] = rule
    return [rules[k] for k in sorted(rules)]


def check_rules(
    rules: list[Rule],
    fields: dict[str, Any],
    tables: dict[str, dict[str, Any]],
    *,
    field_units: dict[str, str | None] | None = None,
) -> list[Finding]:
    """Run rules over extracted fields and tables.

    ``fields`` maps field name -> numeric-or-string value. ``tables`` maps
    table name -> {"columns": [...], "rows": [[...], ...]}.
    """
    findings: list[Finding] = []
    field_units = field_units or {}
    for rule in rules:
        findings.extend(_check_one(rule, fields, tables, field_units))
    return findings


def _check_one(
    rule: Rule,
    fields: dict[str, Any],
    tables: dict[str, dict[str, Any]],
    field_units: dict[str, str | None],
) -> list[Finding]:
    p = rule.params
    if rule.type == "range":
        out: list[Finding] = []
        for name in _targets(p.get("field"), p.get("fields"), fields):
            value = _as_number(fields.get(name))
            if value is None:
                continue
            lo, hi = p.get("min"), p.get("max")
            if (lo is not None and value < lo) or (hi is not None and value > hi):
                out.append(
                    Finding(
                        rule.id,
                        rule.severity,
                        rule.message or f"{name}={value} outside [{lo}, {hi}]",
                        field_name=name,
                    )
                )
        # Same check per table column when the rule names one.
        for table_name, table in _tables(p.get("field"), p.get("fields"), tables).items():
            col = p.get("column")
            if col not in table["columns"]:
                continue
            ci = table["columns"].index(col)
            for ri, row in enumerate(table["rows"]):
                value = _as_number(row[ci] if ci < len(row) else None)
                if value is None:
                    continue
                lo, hi = p.get("min"), p.get("max")
                if (lo is not None and value < lo) or (hi is not None and value > hi):
                    out.append(
                        Finding(
                            rule.id,
                            rule.severity,
                            rule.message or f"{col}={value} outside [{lo}, {hi}]",
                            table_name=table_name,
                            row_index=ri,
                            col_index=ci,
                        )
                    )
        return out

    if rule.type == "format":
        pattern = p.get("regex", "")
        out = []
        for name in _targets(p.get("field"), p.get("fields"), fields):
            value = fields.get(name)
            if value is None:
                continue
            text = str(value)
            if re.fullmatch(pattern, text) is None:
                out.append(
                    Finding(
                        rule.id,
                        rule.severity,
                        rule.message or f"{name}={text!r} does not match {pattern!r}",
                        field_name=name,
                    )
                )
        for table_name, table in _tables(p.get("field"), p.get("fields"), tables).items():
            col = p.get("column")
            if col not in table["columns"]:
                continue
            ci = table["columns"].index(col)
            for ri, row in enumerate(table["rows"]):
                value = row[ci] if ci < len(row) else None
                if value is None:
                    continue
                if re.fullmatch(pattern, str(value)) is None:
                    out.append(
                        Finding(
                            rule.id,
                            rule.severity,
                            rule.message or f"{col}={value!r} does not match {pattern!r}",
                            table_name=table_name,
                            row_index=ri,
                            col_index=ci,
                        )
                    )
        return out

    if rule.type == "cross_field":
        out = []
        formula = p["formula"]
        target = p["target"]
        tolerance = float(p.get("tolerance", 0.1))
        variables = _formula_variables(formula)
        contexts: list[tuple[str | None, int | None, dict[str, float]]] = []
        only_table = p.get("table")
        fields_only = p.get("scope") == "fields"
        pool = {} if fields_only else ({only_table: tables[only_table]} if only_table else tables)
        for tname, table in pool.items():
            cols = table["columns"]
            for ri, row in enumerate(table["rows"]):
                ctx = {}
                wanted = (variables + [target]) if target and target not in variables else variables
                for var in wanted:
                    if var in cols:
                        ci = cols.index(var)
                        value = _as_number(row[ci] if ci < len(row) else None)
                        if value is not None:
                            ctx[var] = value
                if all(v in ctx for v in variables):
                    contexts.append((tname, ri, ctx))
        if not contexts and all(v in fields for v in variables + ([target] if target else [])):
            ctx = {}
            for var in set(variables + ([target] if target else [])):
                num = _as_number(fields[var])
                if num is not None:
                    ctx[var] = num
            if all(v in ctx for v in variables):
                contexts.append((None, None, ctx))
        for src_table, src_row, ctx in contexts:
            expected = _eval_formula(formula, ctx)
            if expected is None:
                continue
            actual = ctx.get(target)
            if actual is None:
                continue
            if expected != 0 and abs(actual - expected) > tolerance * abs(expected):
                out.append(
                    Finding(
                        rule.id,
                        rule.severity,
                        rule.message
                        or f"{target}={actual} inconsistent with {formula}={expected:.4g} "
                        f"(tolerance {tolerance:.0%})",
                        table_name=src_table,
                        row_index=src_row,
                    )
                )
        return out

    if rule.type == "uniqueness":
        out = []
        for table_name, table in _tables(p.get("field"), p.get("fields"), tables).items():
            for col in p.get("columns") or ([p.get("column")] if p.get("column") else []):
                if col not in table["columns"]:
                    continue
                ci = table["columns"].index(col)
                seen: dict[str, int] = {}
                for ri, row in enumerate(table["rows"]):
                    value = row[ci] if ci < len(row) else None
                    if value is None:
                        continue
                    key = str(value).strip().upper()
                    if key in seen:
                        msg = rule.message or (
                            f"duplicate {col}={value!r} in rows {seen[key]} and {ri}"
                        )
                        out.append(
                            Finding(
                                rule.id,
                                rule.severity,
                                msg,
                                table_name=table_name,
                                row_index=ri,
                                col_index=ci,
                            )
                        )
                    else:
                        seen[key] = ri
        return out

    if rule.type == "row_count":
        out = []
        for tname in p.get("tables") or ([p["table"]] if p.get("table") else tables):
            tbl = tables.get(tname)
            if tbl is None:
                continue
            n = len(tbl["rows"])
            lo, hi = p.get("min"), p.get("max")
            if (lo is not None and n < lo) or (hi is not None and n > hi):
                out.append(
                    Finding(
                        rule.id,
                        rule.severity,
                        rule.message or f"table {tname!r} has {n} rows, expected [{lo}, {hi}]",
                        table_name=tname,
                    )
                )
        return out

    if rule.type == "unit_match":
        out = []
        expected_unit = str(p.get("unit", "")).lower()
        for name in _targets(p.get("field"), p.get("fields"), fields):
            unit = (field_units.get(name) or "").strip().lower()
            if unit and unit != expected_unit:
                out.append(
                    Finding(
                        rule.id,
                        rule.severity,
                        rule.message or f"{name}: unit {unit!r} does not match {expected_unit!r}",
                        field_name=name,
                    )
                )
        return out

    return [Finding(rule.id, "error", f"unhandled rule type {rule.type!r}")]


def _targets(
    single: str | None, many: list[str] | None, fields: dict[str, Any]
) -> list[str]:
    names = many if many else ([single] if single else [])
    return [n for n in names if n in fields]


def _tables(
    single: str | None, many: list[str] | None, tables: dict[str, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    names = many or ([single] if single else list(tables))
    return {n: tables[n] for n in names if n in tables}


def _formula_variables(formula: str) -> list[str]:
    """Named operands of a cross-field formula (ast-based, safe)."""
    names: list[str] = []
    for node in ast.walk(ast.parse(formula, mode="eval")):
        if isinstance(node, ast.Name):
            names.append(node.id)
    return sorted(set(names))


_ALLOWED_NODES = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant, ast.Name,
                  ast.Add, ast.Sub, ast.Mult, ast.Div, ast.USub, ast.UAdd, ast.Pow)


def _eval_formula(formula: str, variables: dict[str, float]) -> float | None:
    """Evaluate a cross-field formula. Only arithmetic on named variables."""
    try:
        tree = ast.parse(formula, mode="eval")
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            return None
        if isinstance(node, ast.Constant) and not isinstance(node.value, (int, float)):
            return None
    env = {**variables, "__builtins__": {}}  # noqa: S307 - evaluated on a whitelisted AST
    try:
        return float(eval(compile(tree, "<formula>", "eval"), env))  # noqa: S307
    except (ZeroDivisionError, OverflowError, NameError, SyntaxError):
        return None


def _as_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(" ", "")
    try:
        return float(text)
    except ValueError:
        return None
