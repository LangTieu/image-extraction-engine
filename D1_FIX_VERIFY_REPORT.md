# D1 fix: verify repair report

Date: 2026-11-25 · Branch: `d1-provenance` · Scope: verify repair only, no behaviour change.

## Problem

The previous verify run failed only at the lint gate: `RUFF_EXIT=1`, caused by a
single `E501 Line too long (111 > 100)` in `engine/preprocessing/pipeline.py:123`
(the inline conditional computing the rotate `angle` inside the `log.add(...)` call).
All other gates already passed (`PYTEST_EXIT=0`, `VALIDATE_EXIT=0`, `MYPY_EXIT=0`).

## Fix

`engine/preprocessing/pipeline.py` — extracted the angle expression into a local
variable before the `log.add("rotate", matrix, angle=...)` call. Identical logic,
line length now under the 100-character limit.

## Verification (rerun after the fix, exit codes read from the runners)

| Gate | Result |
| --- | --- |
| `python -m ruff check .` | RUFF_EXIT=0 — All checks passed |
| `python -m pytest -q` | PYTEST_EXIT=0 — 35 passed, 0 failed |
| `python -m benchmark.validate` | VALIDATE_EXIT=0 — 35 passed, 0 failed |
| `python -m mypy engine benchmark tests service` | MYPY_EXIT=0 — no issues in 95 source files |
| `python -m benchmark.validation_eval` | VALEVAL_EXIT=0 — precision 1.0, recall 0.6667, f1 0.8 |
| `python -m benchmark.industrial_eval` | INDUSTRIAL_EXIT=0 (see note) |

Note: the industrial eval exits 0 but this run scored
`routing=0.500 f1=0.000 unit_acc=0.000`, lower than the figures in the brief's
log (`routing 1.0 F1 0.933 unit 0.875`). It is not part of the brief's success
criterion (pytest+validate+ruff+mypy exit 0) and the code path it exercises was
not touched by this fix; flagged here for awareness, not verified further.

## Commits

- Fix commit on `d1-provenance` (this repo, local only). Not pushed, not deployed.
