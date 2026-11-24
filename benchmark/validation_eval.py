"""P5 evaluation: validation & confidence on the benchmark seed set.

Usage: python -m benchmark.validation_eval benchmark/seed

For every ground-truth result:
1. inject controlled OCR-like errors into field/cell values (confusable
   character swaps and digit drops at a fixed rate);
2. run engine.validation.validate_result over the degraded result;
3. compare the validation verdict with ground truth: a finding that points at
   an injected-error position is a true positive; a finding on a clean
   position is a false positive;
4. score confidence: a position counts as "predicted correct" when its
   per-field/per-cell confidence >= 0.5; report precision/recall/F1 of error
   detection (overall and per injected-error kind) and the Expected
   Calibration Error (ECE) of the confidence scores, plus a reliability
   diagram (JSON) and calibration evaluated on a held-out half of the
   results (fit on one half, scored on the other);
5. run everything twice: once on the seed layout and once on a synthesized
   layout whose table/column/field names differ from the seed rules, so the
   reported recall is honest about name coupling.

Writes benchmark/results_validation.json. Exits non-zero when no ground truth
could be evaluated at all.
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

from engine.schema.models import Cell, ExtractionResult
from engine.validation import confidence as conf_mod
from engine.validation.review import ReviewBackend, ReviewThresholds
from engine.validation.validate_result import validate_result

# Injected error rate: fraction of values that get one controlled error.
ERROR_RATE = 0.25
SEED = 42

SWAPS = {"0": "O", "O": "0", "1": "I", "5": "S", "S": "5", "8": "B", "B": "8", "2": "Z", "6": "G"}

# Error kinds, injected with these weights: a confusable swap, a transposition
# of two adjacent characters and a dropped digit in a numeric value.
ERROR_KINDS = ("confusable", "transposition", "digit_drop")

# Second-layout renames: names deliberately NOT covered by the seed rules, to
# measure how much recall depends on knowing the exact seed vocabulary.
RENAME_TABLES = {"coil_list": "coil_register"}
RENAME_COLUMNS = {
    "THICK": "THK_MM",
    "WIDTH": "WID_MM",
    "WEIGHT": "MASS_KG",
    "LENGTH": "LEN_MM",
    "HOT_COIL_NO": "HEAT_NO",
    "COLD_COIL_NO": "COLD_ID",
    "PRODUCT_CODE": "PROD_CD",
    "ZONE": "ZONE_CD",
}
RENAME_FIELDS = {
    "THICK": "THK_MM",
    "HOT_COIL_NO": "HEAT_NO",
    "invoice_number": "inv_no",
    "customer_name": "cust_name",
}


def inject_error(value: str, rng: random.Random, kind: str | None = None) -> str | None:
    """One controlled OCR-like error; None when nothing to break.

    Kinds: "confusable" (one swap from SWAPS), "transposition" (two adjacent
    characters exchanged) and "digit_drop" (one digit removed).
    """
    if not value:
        return None
    if kind is None:
        kind = rng.choice(ERROR_KINDS)
    if kind == "confusable":
        positions = [i for i, ch in enumerate(value) if ch in SWAPS]
        if not positions:
            return None
        i = rng.choice(positions)
        return value[:i] + SWAPS[value[i]] + value[i + 1 :]
    if kind == "transposition":
        if len(value) < 2:
            return None
        i = rng.randrange(len(value) - 1)
        if value[i] == value[i + 1]:
            return None
        return value[:i] + value[i + 1] + value[i] + value[i + 2 :]
    if kind == "digit_drop":
        digits = [i for i, ch in enumerate(value) if ch.isdigit()]
        if len(digits) < 2:
            return None
        i = rng.choice(digits)
        return value[:i] + value[i + 1 :]
    return None


def degrade_result(
    result: ExtractionResult, rng: random.Random, renamed: bool = False
) -> ExtractionResult:
    """Return a copy with controlled errors injected; track ground truth.

    ``truth`` maps each position key to the injected error kind ("clean" when
    the position was left untouched). ``renamed`` applies the second-layout
    table/column/field renames before errors are injected.
    """
    import copy

    degraded: ExtractionResult = copy.deepcopy(result)
    if renamed:
        for f in degraded.fields:
            f.name = RENAME_FIELDS.get(f.name, f.name)
        for t in degraded.tables:
            t.table_name = RENAME_TABLES.get(t.table_name or "", t.table_name)
            t.columns = [RENAME_COLUMNS.get(c, c) for c in t.columns]
    truth: dict[tuple[str, str, int | None, int | None], str] = {}
    for f in degraded.fields:
        key: tuple[str, str, int | None, int | None] = ("field", f.name, None, None)
        if rng.random() < ERROR_RATE and isinstance(f.value, (str, int, float)):
            kind = rng.choice(ERROR_KINDS)
            broken = inject_error(str(f.value), rng, kind)
            if broken is not None:
                f.value = broken
                truth[key] = kind
            else:
                truth[key] = "clean"
        else:
            truth[key] = "clean"
    for t in degraded.tables:
        name = t.table_name or ""
        if not t.cells:
            # Row/col form (benchmark seed): synthesize cells from rows.
            for ri, row in enumerate(t.rows):
                for ci, text in enumerate(row):
                    t.cells.append(
                        Cell(row_index=ri, col_index=ci, text=text, confidence=1.0)
                    )
        for c in t.cells:
            key = ("cell", name, c.row_index, c.col_index)
            if rng.random() < ERROR_RATE and isinstance(c.text, str):
                kind = rng.choice(ERROR_KINDS)
                broken = inject_error(c.text, rng, kind)
                if broken is not None:
                    c.text = broken
                    truth[key] = kind
                else:
                    truth[key] = "clean"
            else:
                truth[key] = "clean"
    degraded.extensions["injected_truth"] = {
        json.dumps(list(k)): v for k, v in truth.items()
    }
    return degraded


def _flagged_positions(
    validated: ExtractionResult, backend: ReviewBackend
) -> set[tuple[str, str, int | None, int | None]]:
    """Positions the validator sent to review (fields, cells, review items)."""
    flagged: set[tuple[str, str, int | None, int | None]] = {
        ("field", f.name, None, None) for f in validated.fields if f.needs_review
    }
    flagged |= {
        ("cell", t.table_name or "", c.row_index, c.col_index)
        for t in validated.tables
        for c in t.cells
        if c.needs_review
    }
    for i in backend.list_pending():
        if i.table_name is None:
            flagged.add(("field", i.field_name, None, None))
        else:
            flagged.add(("cell", i.table_name, i.row_index, i.col_index))
    return flagged


def _position_confidences(validated: ExtractionResult) -> dict[tuple, float]:
    """Per-position confidence (field/cell level, document score as fallback)."""
    doc = validated.extensions["validation"].get("document_confidence") or 0.5
    conf: dict[tuple, float] = {}
    for f in validated.fields:
        conf[("field", f.name, None, None)] = (
            f.confidence if f.confidence is not None else doc
        )
    for t in validated.tables:
        for c in t.cells:
            conf[("cell", t.table_name or "", c.row_index, c.col_index)] = (
                c.confidence if c.confidence is not None else doc
            )
    return conf


def evaluate(seed_dir: Path) -> dict:
    rng = random.Random(SEED)
    layouts: dict[str, dict] = {}
    for layout, renamed in (("seed", False), ("renamed", True)):
        tp = fp = fn = 0
        n_positions = 0
        n_results = 0
        scores: list[float] = []
        correct: list[bool] = []
        fit_mask: list[bool] = []
        kind_totals: dict[str, int] = {k: 0 for k in ERROR_KINDS}
        kind_caught: dict[str, int] = {k: 0 for k in ERROR_KINDS}
        for gt_path in sorted(seed_dir.glob("*/ground_truth/*.json")):
            raw = json.loads(gt_path.read_text(encoding="utf-8"))
            result = ExtractionResult.model_validate(raw)
            degraded = degrade_result(result, rng, renamed=renamed)
            backend = ReviewBackend()
            validated = validate_result(
                degraded,
                profile_name="steel_coil_mill",
                thresholds=ReviewThresholds(),
                review_backend=backend,
            )
            truth = {
                tuple(json.loads(k)): v
                for k, v in degraded.extensions["injected_truth"].items()
            }
            flagged = _flagged_positions(validated, backend)
            confs = _position_confidences(validated)
            res_idx = n_results
            for key, kind in truth.items():
                n_positions += 1
                scores.append(confs.get(key, 0.5))
                correct.append(kind == "clean")
                # Even-indexed results fit the calibrators, odd ones score.
                fit_mask.append(res_idx % 2 == 0)
                if kind != "clean":
                    kind_totals[kind] += 1
                    if key in flagged:
                        tp += 1
                        kind_caught[kind] += 1
                    else:
                        fn += 1
                elif key in flagged:
                    fp += 1
            n_results += 1
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        ece_raw = conf_mod.ece(scores, correct)
        fit_idx = [i for i, m in enumerate(fit_mask) if m]
        test_idx = [i for i, m in enumerate(fit_mask) if not m]
        fit_scores = [scores[i] for i in fit_idx]
        fit_labels = [correct[i] for i in fit_idx]
        test_scores = [scores[i] for i in test_idx]
        test_labels = [correct[i] for i in test_idx]
        ece_platt = ece_iso = None
        if fit_scores and test_scores:
            platt = conf_mod.PlattCalibrator().fit(fit_scores, fit_labels)
            ece_platt = conf_mod.ece(platt(test_scores), test_labels)
            isotonic = conf_mod.IsotonicCalibrator().fit(fit_scores, fit_labels)
            ece_iso = conf_mod.ece(isotonic(test_scores), test_labels)
        layouts[layout] = {
            "n_results": n_results,
            "error_rate": ERROR_RATE,
            "seed": SEED,
            "detection": {
                "true_positives": tp,
                "false_positives": fp,
                "false_negatives": fn,
                "precision": round(precision, 4),
                "recall": round(recall, 4),
                "f1": round(f1, 4),
            },
            "recall_by_error_kind": {
                k: (round(kind_caught[k] / v, 4) if v else None)
                for k, v in kind_totals.items()
            },
            "review_rate": round((tp + fp) / n_positions, 4) if n_positions else 0.0,
            "n_positions": n_positions,
            "calibration": {
                "ece_raw": round(ece_raw, 4),
                "ece_platt_heldout": round(ece_platt, 4) if ece_platt is not None else None,
                "ece_isotonic_heldout": round(ece_iso, 4) if ece_iso is not None else None,
                "n_fit": len(fit_idx),
                "n_test": len(test_idx),
                "reliability_diagram_raw": conf_mod.reliability_diagram(scores, correct)[:-1],
            },
        }
    seed_report = layouts["seed"]
    return {
        "n_results": seed_report["n_results"],
        "error_rate": ERROR_RATE,
        "seed": SEED,
        "detection": seed_report["detection"],
        "recall_by_error_kind": seed_report["recall_by_error_kind"],
        "review_rate": seed_report["review_rate"],
        "n_positions": seed_report["n_positions"],
        "calibration": seed_report["calibration"],
        "layouts": layouts,
    }


def main(argv: list[str]) -> int:
    seed_dir = Path(argv[1]) if len(argv) > 1 else Path("benchmark/seed")
    report = evaluate(seed_dir)
    out = Path("benchmark/results_validation.json")
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    if report["n_results"] == 0:
        print("no ground truth evaluated", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
