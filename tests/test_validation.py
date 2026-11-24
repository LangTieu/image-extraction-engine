"""Tests for the P5 validation layer (user requested explicitly).

Covers:
- the sandboxed formula evaluator (safe arithmetic, rejects everything else)
- rule-ID collisions across YAML files (warn, never silent overwrite)
- a digit-permuted table cell flowing through ``validate_result``
- confusable-character proposals: proposed, never silently applied
- Platt calibration fit on a train half, ECE measured on a held-out half
- the full ``validate_result`` pipeline wiring (normalize → dynamic schema →
  rules → ambiguity) and the name-agnostic NUMERIC_ANY_RANGE scan
- thousands-separator grouping that stays ambiguous (``12,34``)
"""

from __future__ import annotations

import importlib
import logging
from pathlib import Path

import pytest

from engine.schema.models import (
    Cell,
    ExtractionResult,
    ExtractionStatus,
    FieldValue,
    Table,
)
from engine.validation import rules as rules_mod
from engine.validation.confidence import (
    IsotonicCalibrator,
    PlattCalibrator,
    ece,
)
from engine.validation.normalize import normalize_number
from engine.validation.review import ReviewBackend

# The package __init__ re-exports the ``validate_result`` *function* under the
# same name as the submodule, so grab the module itself explicitly.
vr_module = importlib.import_module("engine.validation.validate_result")
validate_result = vr_module.validate_result


def make_result(
    fields: list[FieldValue] | None = None,
    tables: list[Table] | None = None,
) -> ExtractionResult:
    return ExtractionResult(
        document_type="industrial_hmi",
        extraction_status=ExtractionStatus.COMPLETED,
        job_id="job-p5",
        fields=fields or [],
        tables=tables or [],
    )


def make_table(
    name: str,
    columns: list[str],
    rows: list[list[str | None]],
) -> Table:
    cells = [
        Cell(row_index=r, col_index=c, text=v, confidence=0.99)
        for r, row in enumerate(rows)
        for c, v in enumerate(row)
    ]
    return Table(table_name=name, columns=columns, rows=rows, cells=cells)


# ---------------------------------------------------------------------------
# (a) Formula evaluator: arithmetic only.
# ---------------------------------------------------------------------------


def test_eval_formula_arithmetic_only():
    ctx = {"THICK": 2.0, "WIDTH": 3.0, "LENGTH": 1000.0}
    assert rules_mod._eval_formula("THICK * WIDTH * 2", ctx) == 12.0
    assert rules_mod._eval_formula("THICK + WIDTH", ctx) == 5.0
    assert rules_mod._eval_formula("(THICK * WIDTH * LENGTH) / 1000", ctx) == 6.0
    assert rules_mod._eval_formula("-THICK + WIDTH", ctx) == 1.0


def test_eval_formula_comparisons_return_bool():
    ctx = {"THICK": 2.0, "WIDTH": 3.0}
    assert rules_mod._eval_formula("WIDTH > THICK", ctx) is True
    assert rules_mod._eval_formula("THICK < WIDTH", ctx) is True
    assert rules_mod._eval_formula("THICK < WIDTH", ctx) is not None
    assert rules_mod._eval_formula("WIDTH < THICK", ctx) is False
    assert rules_mod._eval_formula("THICK >= 2.0", ctx) is True
    assert rules_mod._eval_formula("THICK == 2.0", ctx) is True
    assert rules_mod._eval_formula("THICK != WIDTH", ctx) is True


@pytest.mark.parametrize(
    "expr",
    [
        "__import__('os')",  # function call
        "open('/etc/passwd')",  # call on a builtin name
        "THICK.__class__",  # attribute access
        "open('/etc/passwd')",  # call on a builtin name
        "THICK *",  # syntax error
        "THICK * MISSING",  # unknown name
        "",  # empty expression
    ],
)
def test_eval_formula_rejects_unsafe(expr):
    ctx = {"THICK": 2.0, "WIDTH": 3.0}
    assert rules_mod._eval_formula(expr, ctx) is None


# ---------------------------------------------------------------------------
# (b) Rule-ID collision across YAML files: warn, and both rules still run.
# ---------------------------------------------------------------------------


def write_rule_yaml(path: Path, rule: dict) -> None:
    import yaml

    path.write_text(yaml.safe_dump({"rules": [rule]}), encoding="utf-8")


def test_duplicate_rule_id_warns_and_profile_def_wins(tmp_path, caplog):
    write_rule_yaml(
        tmp_path / "default.yaml",
        {
            "id": "R_TEMP_RANGE",
            "type": "range",
            "severity": "error",
            "message": "base range",
            "params": {"field": "TEMP", "min": 0, "max": 100},
        },
    )
    write_rule_yaml(
        tmp_path / "prof.yaml",
        {
            "id": "R_TEMP_RANGE",
            "type": "range",
            "severity": "warning",
            "message": "profile range",
            "params": {"field": "TEMP", "min": -50, "max": 100},
        },
    )

    with caplog.at_level(logging.WARNING, logger="engine.validation.rules"):
        loaded = rules_mod.load_rules("prof", directory=tmp_path)

    assert any("duplicate rule id" in rec.message.lower() for rec in caplog.records)
    assert any("R_TEMP_RANGE" in rec.message for rec in caplog.records)
    # No silent overwrite: the collision is visible, and the profile file
    # (loaded last) decides which definition wins.
    assert len(loaded) == 1
    assert loaded[0].message == "profile range"
    assert loaded[0].severity == "warning"


def test_rules_from_all_yaml_files_run(tmp_path):
    write_rule_yaml(
        tmp_path / "default.yaml",
        {
            "id": "R_TEMP_RANGE",
            "type": "range",
            "severity": "error",
            "message": "base range",
            "params": {"field": "TEMP", "min": 0, "max": 100},
        },
    )
    write_rule_yaml(
        tmp_path / "prof.yaml",
        {
            "id": "R_CODE_FORMAT",
            "type": "format",
            "severity": "error",
            "message": "code format",
            "params": {"field": "CODE", "regex": "[0-9]+"},
        },
    )
    loaded = rules_mod.load_rules("prof", directory=tmp_path)
    assert {r.id for r in loaded} == {"R_TEMP_RANGE", "R_CODE_FORMAT"}

    findings = rules_mod.check_rules(loaded, {"TEMP": -5, "CODE": "X12A"}, [])
    rule_ids = {f.rule_id for f in findings}
    assert {"R_TEMP_RANGE", "R_CODE_FORMAT"} <= rule_ids


# ---------------------------------------------------------------------------
# (c) Digit-permuted numeric cell gets flagged end-to-end.
# ---------------------------------------------------------------------------


def test_transposed_digit_cell_flagged(tmp_path):
    write_rule_yaml(
        tmp_path / "default.yaml",
        {
            "id": "P5_WEIGHT_XCHECK",
            "type": "cross_field",
            "severity": "error",
            "message": "weight does not match dimensions",
            "params": {
                "table": "coil_list",
                "target": "WEIGHT",
                "formula": "THICK * LENGTH",
                "tolerance": 0.05,
            },
        },
    )
    # Row 0 is consistent (2.0 * 617.0 = 1234.0); row 1 has the OCR read
    # "1324" — the digits of 1234 permuted.
    table = make_table(
        "coil_list",
        ["THICK", "LENGTH", "WEIGHT"],
        [["2.0", "617.0", "1234"], ["2.0", "617.0", "1324"]],
    )
    result = make_result(tables=[table])
    out = validate_result(result, rules_dir=str(tmp_path))

    assert "P5_WEIGHT_XCHECK" in out.extensions["validation"]["rule_ids"]
    assert out.extraction_status.value == "needs_review"
    # The consistent row stays untouched.
    good_cell = next(
        c for c in out.tables[0].cells if c.row_index == 0 and c.col_index == 2
    )
    assert good_cell.needs_review is False


def test_numeric_any_range_catches_renamed_column(tmp_path):
    # A numeric column with a name the deployment never declared still gets
    # bounded by the name-agnostic scan.
    table = make_table("mystery", ["X9", "UNITS"], [["1.5", "42"], ["2.5", "9999999"]])
    result = make_result(tables=[table])
    out = validate_result(result)  # default rules, no rules_dir override

    assert "NUMERIC_ANY_RANGE" in out.extensions["validation"]["rule_ids"]


# ---------------------------------------------------------------------------
# (d) Confusable characters: propose, never silently apply.
# ---------------------------------------------------------------------------


def test_ambiguity_proposal_not_applied(tmp_path):
    write_rule_yaml(
        tmp_path / "default.yaml",
        {
            "id": "P5_ID_FORMAT",
            "type": "format",
            "severity": "error",
            "message": "id format",
            "params": {"field": "COIL_NO", "regex": "[0-9]{6}"},
        },
    )
    field = FieldValue(name="COIL_NO", value="1O3456")  # O/0 confusion
    result = make_result(fields=[field])
    out = validate_result(result, rules_dir=str(tmp_path))

    assert out.fields[0].value == "1O3456"  # original value untouched
    assert out.fields[0].proposals == ["103456"]  # exactly one safe reading
    assert out.fields[0].needs_review is True
    assert "AMBIGUITY_PROPOSED" in out.extensions["validation"]["rule_ids"]
    note = out.extensions["validation"]["ambiguity"]["COIL_NO"]
    assert note["status"] == "proposed"
    assert note["raw"] == "1O3456"
    assert out.extraction_status.value == "needs_review"


def test_ambiguity_no_safe_reading(tmp_path):
    write_rule_yaml(
        tmp_path / "default.yaml",
        {
            "id": "P5_ID_FORMAT",
            "type": "format",
            "severity": "error",
            "message": "id format",
            "params": {"field": "COIL_NO", "regex": "[0-9]{6}"},
        },
    )
    # Confusable plus a non-confusable stray character: no single safe
    # substitution can repair it, so nothing is proposed.
    field = FieldValue(name="COIL_NO", value="1O345X")
    result = make_result(fields=[field])
    out = validate_result(result, rules_dir=str(tmp_path))

    assert out.fields[0].value == "1O345X"
    assert out.fields[0].proposals == []
    assert "AMBIGUOUS_VALUE" in out.extensions["validation"]["rule_ids"]


def test_ambiguity_proposals_reach_review_items(tmp_path):
    write_rule_yaml(
        tmp_path / "default.yaml",
        {
            "id": "P5_ID_FORMAT",
            "type": "format",
            "severity": "error",
            "message": "id format",
            "params": {"field": "COIL_NO", "regex": "[A-Z][0-9]{2}-[0-9]{4}"},
        },
    )
    backend = ReviewBackend()
    result = make_result(fields=[FieldValue(name="COIL_NO", value="H26-OI42")])
    out = validate_result(result, rules_dir=str(tmp_path), review_backend=backend)

    items = list(backend.items.values())
    assert len(items) == 1
    assert items[0].field_name == "COIL_NO"
    assert items[0].proposals == ["H26-0142"]  # carried through, not dropped
    assert out.extensions["validation"]["review_item_ids"] == [items[0].item_id]


def test_flagged_cell_gets_review_item(tmp_path):
    write_rule_yaml(
        tmp_path / "default.yaml",
        {
            "id": "P5_WIDTH_RANGE",
            "type": "format",
            "severity": "error",
            "message": "width out of range",
            "params": {"table": "coil_list", "column": "WIDTH", "regex": "[0-9]{1,4}"},
        },
    )
    backend = ReviewBackend()
    table = make_table("coil_list", ["THICK", "WIDTH"], [["2.0", "9999999"]])
    result = make_result(tables=[table])
    out = validate_result(result, rules_dir=str(tmp_path), review_backend=backend)

    items = list(backend.items.values())
    assert any(
        i.table_name == "coil_list" and i.col_index == 1 for i in items
    )
    assert out.tables[0].cells[1].needs_review is True


# ---------------------------------------------------------------------------
# (e) Calibration: fit on a train half, measure ECE on a held-out half.
# ---------------------------------------------------------------------------


def test_platt_calibration_improves_holdout_ece():
    # Labels are deliberately shifted: truth is s > 0.5 while the raw score
    # claims confidence s, so the model is miscalibrated in a fixable way.
    train_scores = [0.2, 0.3, 0.4, 0.6, 0.7, 0.8]
    train_labels = [s > 0.5 for s in train_scores]
    test_scores = [0.1, 0.3, 0.45, 0.55, 0.7, 0.9]
    test_labels = [s > 0.5 for s in test_scores]

    raw_ece = ece(test_scores, test_labels)

    cal = PlattCalibrator()
    cal.fit(train_scores, train_labels)  # train half only
    assert (cal.a, cal.b) != (1.0, 0.0)  # the fit actually moved

    calibrated = cal(test_scores)
    assert calibrated != test_scores
    calibrated_ece = ece(calibrated, test_labels)

    assert calibrated_ece < raw_ece


def test_isotonic_calibration_is_monotone():
    scores = [0.1, 0.2, 0.3, 0.4, 0.6, 0.7, 0.8, 0.9]
    labels = [False, False, False, True, True, True, True, True]
    cal = IsotonicCalibrator().fit(scores, labels)
    out = cal(scores)
    assert all(o <= n for o, n in zip(out, out[1:]))


# ---------------------------------------------------------------------------
# (f) Pipeline wiring: normalize → dynamic schema → rules → ambiguity.
# ---------------------------------------------------------------------------


def test_validate_result_wires_all_stages(monkeypatch):
    calls: dict[str, int] = {"normalize": 0, "ambiguity": 0, "schema": 0}

    real_normalize = vr_module.normalize_field
    real_resolve = vr_module.resolve_ambiguity

    def normalize_spy(*args, **kwargs):
        calls["normalize"] += 1
        return real_normalize(*args, **kwargs)

    def resolve_spy(*args, **kwargs):
        calls["ambiguity"] += 1
        return real_resolve(*args, **kwargs)

    import engine.validation.dynamic_schema as ds

    real_validate_fields = ds.validate_fields

    def schema_spy(*args, **kwargs):
        calls["schema"] += 1
        return real_validate_fields(*args, **kwargs)

    monkeypatch.setattr(vr_module, "normalize_field", normalize_spy)
    monkeypatch.setattr(vr_module, "resolve_ambiguity", resolve_spy)
    monkeypatch.setattr(ds, "validate_fields", schema_spy)

    # width_mm is normalized from OCR text to a number and then checked
    # against the steel_coil_mill profile bounds (200..2500); 99999 must be
    # rejected by the dynamic schema, not trusted.
    fields = [
        FieldValue(name="width_mm", value="99999"),
        FieldValue(name="coil_id", value="1O3456"),
    ]
    result = make_result(fields=fields)
    out = validate_result(result, profile_name="steel_coil_mill")

    assert calls["normalize"] >= 2
    assert calls["ambiguity"] >= 1
    assert calls["schema"] == 1
    rule_ids = out.extensions["validation"]["rule_ids"]
    assert any(rid.startswith("DYNAMIC_") for rid in rule_ids)
    assert out.extraction_status.value == "needs_review"


# ---------------------------------------------------------------------------
# (g) Thousands-separator grouping that stays ambiguous.
# ---------------------------------------------------------------------------


def test_thousands_grouping_ambiguous_never_guessed():
    norm = normalize_number("12,34")
    assert norm.value is None  # 12.34? 1234? neither is safe
    assert any("ambiguous grouping" in n for n in norm.notes)


def test_thousands_grouping_flagged_in_table(tmp_path):
    write_rule_yaml(
        tmp_path / "default.yaml",
        {
            "id": "P5_QTY_FORMAT",
            "type": "format",
            "severity": "error",
            "message": "qty must be a plain number",
            "params": {"table": "orders", "column": "QTY", "regex": "[0-9]+(\\.[0-9]+)?"},
        },
    )
    table = make_table("orders", ["QTY", "NOTE"], [["12,34", "ok"], ["1200", "ok"]])
    result = make_result(tables=[table])
    out = validate_result(result, rules_dir=str(tmp_path))

    assert "P5_QTY_FORMAT" in out.extensions["validation"]["rule_ids"]
    bad_cell = next(
        c for c in out.tables[0].cells if c.row_index == 0 and c.col_index == 0
    )
    assert bad_cell.needs_review is True
