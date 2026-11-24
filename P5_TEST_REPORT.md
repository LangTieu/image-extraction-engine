# P5 Test Report

Branch: `p5-review`. Deliverable per `mlai_p5_test_brief.md`: `tests/test_validation.py`.

## Test file

`tests/test_validation.py` — 22 tests covering the P5 validation layer:

1. Formula sandbox (`rules._eval_formula`): arithmetic only (calls, attribute
   access, unknown names, syntax errors, non-numeric constants rejected);
   comparison formulas return real booleans.
2. Rule-ID collisions across YAML files: a "duplicate rule id" warning is
   logged and the profile-file definition wins (no silent overwrite); rules
   with distinct IDs from `default.yaml` + `<profile>.yaml` all run.
3. Digit-permuted numeric cell (`1234` → `1324`) in a numeric column is caught
   end-to-end by `validate_result` (cross-field finding, needs_review, result
   status); the name-agnostic `NUMERIC_ANY_RANGE` scan catches an undeclared
   numeric column.
4. Confusable characters: `1O3456` keeps its raw value, proposes exactly
   `["103456"]`, gets `AMBIGUITY_PROPOSED`; an unrepairable value gets
   `AMBIGUOUS_VALUE` with no proposals; proposals reach the review item
   (`H26-OI42` → item proposals `["H26-0142"]`); a format-failing table cell
   produces a review item.
5. Calibration: Platt and isotonic fitted on a train half, ECE measured on a
   held-out half, holdout ECE strictly improves; isotonic output is monotone.
6. Pipeline wiring proven with spies: normalize → dynamic profile schema →
   rules → ambiguity, plus a `DYNAMIC_` finding on a profile-bound field.
7. Ambiguous thousands grouping `12,34`: `normalize_number` returns no value
   with an "ambiguous grouping" note; the raw text stays in the cell and is
   format-flagged.

## How to run

```
.venv/bin/python -m pytest tests/ -q
.venv/bin/python -m ruff check .
.venv/bin/python -m mypy engine tests
```

## Results (this session, real exit statuses)

- `pytest tests/ -q`: exit 0 — 102 passed (22 in `tests/test_validation.py`).
- `ruff check .`: exit 0 — clean.
- `mypy engine tests`: exit 1 — 1 pre-existing error in
  `tests/test_tables.py:156` (file untouched by this task); `tests/test_validation.py`
  and `engine/` are clean.

## Production fixes (test proved a real bug)

- `engine/validation/rules.py` — `_eval_formula`: `ast.Compare` was missing
  from the AST whitelist while comparison ops were whitelisted, so every
  comparison formula returned `None`; and the result was coerced through
  `float()`, turning booleans into `1.0`/`0.0`. Now `ast.Compare` is allowed
  and a comparison formula returns a real `bool`. (Reproduces and fixes the
  hidden acceptance failure `test_comparison_operators`.)
- `engine/validation/validate_result.py` — `field_flags`/`cell_flags` did not
  carry the `proposals` list, so `ReviewItem.proposals` was always `[]` even
  when the source field/cell had safe candidate readings. Now the proposals
  flow through to review items. (Reproduces and fixes the hidden acceptance
  failure `test_confusable_field_gets_proposal_and_summary`.)

The third reported failure, `test_flagged_cell_gets_review_item`, was an
environment error (`ModuleNotFoundError: No module named 'cv2'`). In this
workspace `opencv-python-headless` is installed (declared in `pyproject.toml`)
and `import cv2` succeeds; the scenario was verified directly: a cell flagged
by an error finding gets a review item (covered by
`test_flagged_cell_gets_review_item` in the new test file).

## Not run

Benchmark suites (`benchmark/`) were not executed; the brief scoped this task
to the validation tests.
