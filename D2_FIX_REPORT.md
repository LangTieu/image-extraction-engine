# D2 fix report — verify round failed on ruff only

The previous verify round failed with `RUFF_EXIT=1` (2 fixable errors); pytest,
validate and mypy were already green. This round fixes exactly that.

## Error
```
F401 [*] `engine.preprocessing.errors.CorruptImageError` imported but unused
  --> engine/preprocessing/io.py:19:5
F401 [*] `engine.preprocessing.errors.UnsupportedFormatError` imported but unused
  --> engine/preprocessing/io.py:19:5 (same import block)
```
Both were ruff autofixable. Verified nothing imports these names from
`engine.preprocessing.io` (only `DEFAULT_DPI`, `LoadedImage`, `load_input`,
`MAX_PIXELS_PER_SIDE`, `_sha256_of`, `_from_pdf` are imported elsewhere), so the
unused imports were removed with `ruff check --fix`. No other file changed.

## Gates (exit codes only, no pipes; logs in /tmp/d2_*.log)
- `pytest tests/ -q` → `PYTEST_EXIT=0`, **174 passed, 0 failed, 0 errors, 0 skipped** (junit XML: `tests="174" failures="0" errors="0" skipped="0"`)
- `python -m benchmark.validate benchmark/seed` → `VALIDATE_EXIT=0` (35 passed, 0 failed)
- `ruff check .` → `RUFF_EXIT=0` ("All checks passed!")
- `mypy engine benchmark service tests` → `MYPY_EXIT=0` ("Success: no issues found in 89 source files")

Note: this environment's pytest does not print the final `N passed` summary line
(output ends at the warnings section); the count above is taken from the JUnit
XML written by the same run, and the exit code decides pass/fail per the brief.

## Commit
`engine/preprocessing/io.py` (2 deleted lines) + this report, committed on
branch `d2-backend-registry`. Not pushed; the liaison merges.

Done — gates: pytest 0, validate 0, ruff 0, mypy 0; 174 tests, 0 failures.
