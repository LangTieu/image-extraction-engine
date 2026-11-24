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
   confidence >= 0.5; report precision/recall/F1 of error detection and the
   Expected Calibration Error (ECE) of the confidence scores, plus a
   reliability diagram (JSON) and the improvement after Platt/isotonic
   calibration.

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

# Injected error rate: fraction of values that get one confusable error.
ERROR_RATE = 0.25
SEED = 42

SWAPS = {"0": "O", "O": "0", "1": "I", "5": "S", "S": "5", "8": "B", "B": "8", "2": "Z", "6": "G"}


def inject_error(value: str, rng: random.Random) -> str | None:
    """One confusable swap or a dropped character; None when nothing to break."""
    positions = [i for i, ch in enumerate(value) if ch in SWAPS or ch.isalnum()]
    if not positions:
        return None
    i = rng.choice(positions)
    ch = value[i]
    if ch in SWAPS:
        return value[:i] + SWAPS[ch] + value[i + 1 :]
    if len(value) > 1:
        return value[:i] + value[i + 1 :]
    return None


def degrade_result(result: ExtractionResult, rng: random.Random) -> ExtractionResult:
    """Return a copy with controlled errors injected; track ground truth."""
    import copy

    degraded: ExtractionResult = copy.deepcopy(result)
    truth: dict[tuple, bool] = {}
    for f in degraded.fields:
        key = ("field", f.name, None, None)
        if isinstance(f.value, str) and rng.random() < ERROR_RATE:
            broken = inject_error(f.value, rng)
            if broken is not None:
                f.value = broken
                truth[key] = True
            else:
                truth[key] = False
        else:
            truth[key] = False
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
            if isinstance(c.text, str) and rng.random() < ERROR_RATE:
                broken = inject_error(c.text, rng)
                if broken is not None:
                    c.text = broken
                    truth[key] = True
                else:
                    truth[key] = False
            else:
                truth[key] = False
    degraded.extensions["injected_truth"] = {
        json.dumps(list(k)): v for k, v in truth.items()
    }
    return degraded


def evaluate(seed_dir: Path) -> dict:
    rng = random.Random(SEED)
    tp = fp = fn = 0
    n_positions = 0
    scores: list[float] = []
    correct: list[bool] = []
    n_results = 0
    for gt_path in sorted(seed_dir.glob("*/ground_truth/*.json")):
        raw = json.loads(gt_path.read_text(encoding="utf-8"))
        result = ExtractionResult.model_validate(raw)
        degraded = degrade_result(result, rng)
        backend = ReviewBackend()
        validated = validate_result(
            degraded,
            profile_name=None,
            thresholds=ReviewThresholds(),
            review_backend=backend,
        )
        truth = {tuple(json.loads(k)): v for k, v in degraded.extensions["injected_truth"].items()}
        flagged = {
            ("field", f.name, None, None) for f in validated.fields if f.needs_review
        }
        flagged |= {
            ("cell", t.table_name or "", c.row_index, c.col_index)
            for t in validated.tables
            for c in t.cells
            if c.needs_review
        }
        # A needs_review table flags every cell whose position carries an
        # error finding; the table row-level verdict maps to those positions.
        for i in backend.list_pending():
            if i.table_name is None:
                flagged.add(("field", i.field_name, None, None))
            else:
                flagged.add(("cell", i.table_name, i.row_index, i.col_index))
        for t in validated.tables:
            if t.needs_review and len(t.cells) < len(t.columns) * max(1, len(t.rows)):
                # Row-form table (cells all clean): the table verdict flags
                # its injected cells via the review items and error findings.
                for i in backend.list_pending():
                    if i.table_name == t.table_name and i.row_index is not None:
                        flagged.add(("cell", i.table_name, i.row_index, i.col_index))
                for f in validated.validation_results:
                    if f.table_name == t.table_name and f.row_index is not None:
                        flagged.add(("cell", t.table_name or "", f.row_index, f.col_index))
        for key, was_error in truth.items():
            n_positions += 1
            scores.append(validated.extensions["validation"]["document_confidence"] or 0.5)
            correct.append(not was_error)
            if was_error:
                if key in flagged:
                    tp += 1
                else:
                    fn += 1
            elif key in flagged:
                fp += 1
        n_results += 1
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    ece_raw = conf_mod.ece(scores, correct)
    platt = conf_mod.PlattCalibrator().fit(scores, correct)
    calibrated = platt(scores)
    ece_platt = conf_mod.ece(calibrated, correct)
    isotonic = conf_mod.IsotonicCalibrator().fit(scores, correct)
    ece_iso = conf_mod.ece(isotonic(scores), correct)
    return {
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
        "review_rate": round((tp + fp) / n_positions, 4) if n_positions else 0.0,
        "n_positions": n_positions,
        "calibration": {
            "ece_raw": round(ece_raw, 4),
            "ece_platt": round(ece_platt, 4),
            "ece_isotonic": round(ece_iso, 4),
            "reliability_diagram_raw": conf_mod.reliability_diagram(scores, correct)[:-1],
        },
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
