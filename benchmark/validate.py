"""Validate the benchmark seed dataset.

Usage: python -m benchmark.validate benchmark/seed

Checks, for every category directory and sample:
- ground_truth JSON parses as a valid ExtractionResult (unified schema);
- document_type is a registered taxonomy category;
- the referenced image file exists on disk;
- table columns stay within the schema and cell rows are rectangular.

Exits non-zero on any error. Warnings do not fail the run.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from engine.schema import ExtractionResult, all_categories


def validate_sample(gt_path: Path) -> list[str]:
    problems: list[str] = []
    raw = json.loads(gt_path.read_text(encoding="utf-8"))
    try:
        result = ExtractionResult.model_validate(raw)
    except Exception as exc:  # pydantic.ValidationError or JSON error
        return [f"{gt_path}: schema validation failed: {exc}"]

    if result.document_type not in all_categories():
        problems.append(f"{gt_path}: unregistered document_type {result.document_type!r}")

    image_dir = gt_path.parent.parent / "images"
    if result.source is None:
        problems.append(f"{gt_path}: missing source info")
    else:
        image = image_dir / result.source.file_name
        if not image.exists():
            problems.append(f"{gt_path}: referenced image not found: {image}")

    for i, table in enumerate(result.tables):
        widths = {len(r) for r in table.rows if r is not None}
        if table.columns and len(widths) > 1:
            problems.append(
                f"{gt_path}: table[{i}] rows are not rectangular: widths={sorted(widths)}"
            )
        if table.columns and any(
            len(r) not in (0, len(table.columns)) for r in table.rows if r is not None
        ):
            problems.append(f"{gt_path}: table[{i}] row length does not match column count")
    return problems


def validate_dataset(root: Path) -> tuple[int, int]:
    """Returns (passed, failed) sample counts; prints a line per sample."""
    passed = failed = 0
    if not root.is_dir():
        print(f"dataset root not found: {root}")
        return 0, 1
    for gt_path in sorted(root.glob("*/ground_truth/*.json")):
        problems = validate_sample(gt_path)
        if problems:
            failed += 1
            for p in problems:
                print(f"ERROR: {p}")
        else:
            passed += 1
            print(f"ok: {gt_path}")
    print(f"\n{passed} passed, {failed} failed")
    return passed, failed


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("benchmark/seed")
    _, failed = validate_dataset(root)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
