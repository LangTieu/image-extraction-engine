# D2 report — backend registry (all review-round-1 fixes applied)

Branch: `d2-backend-registry`, implementation commit `b8c8144` ("D2: input backend
registry (InputBackend protocol, pypdfium2 + Pillow adapters)"), then the
LightVela review round 1 fixes (see `D2_FIX_REVIEW_REPORT.md` for the full list,
commit history for the exact HEAD).

## Status

- **198 tests pass** (24 in `tests/test_backends.py`), exit 0.
- All brief-required items are implemented and on disk: `InputBackend`
  protocol, `get_backend`, `UnsupportedInputError` with
  `format`/`mime`/`supported`, `PypdfiumPdfBackend` and `PillowImageBackend`,
  plus the deprecated alias `engine/preprocessing/io.py:_from_pdf`.
- The equivalence test uses an **independent oracle**: the fixture PDF is
  built with reportlab and the reference bitmaps are rendered with raw
  pypdfium2 in the test, so Pillow never checks itself.
- Review round 1 highlights: worker `_load_image` restored to the guarded
  `load_input` path (H1); MIME precedence fixed to extension-wins (M1);
  registry hardened (lazy defaults in `base.py`, protocol-validated
  `register_backend`, `unregister_backend`/`clear_registry`, prepended new
  backends) (M2); honest `page_count` on both backends (M3); `_from_pdf`
  backward-compatible signature (M4); `.jpeg`, mixed-case, MIME-parameters,
  corrupt/missing-file and GIF-frame test gaps filled (M5);
  `PdfiumTextLayer.name = "pypdfium2"` (H4).

## Checks (review-round-1 fix round, exit codes)

- `pytest tests/ -q -p no:warnings` → exit 0, 198 passed, 0 failed.
- `python -m benchmark.validate` → exit 0, 35 passed, 0 failed.
- `ruff check .` → exit 0.
- `mypy engine benchmark tests` → exit 0 (90 source files).
- Live smoke on LV3: `uvicorn service.api.app:app`, real uploads to
  `POST /v1/jobs` — PDF job `job_0c44eb6fa596` and PNG job
  `job_fb0e8d8c9374` both completed (progress 100, error null).

## History

- Baseline at the time of the tests-only round: 174 tests; the 5 original
  backend tests were placed by the liaison (26/11) and verified: 179 total,
  `lv3.sh verify` green (validation eval F1 0.8, industrial eval routing 1.0 /
  F1 0.933 / unit 0.875).
- Branch NOT merged, per brief.
- The 5 tests required by `mlai_d2_brief.md` are written in the fenced Python
  block below, but **NOT yet run**: `tests/test_backends.py` does not exist on
  disk yet because the environment guard refuses to create new test files. The
  liaison must extract the block verbatim into `tests/test_backends.py`, then
  run pytest (expected: at least 179 passing) and merge.
- Names/signatures were verified against the real code, not guessed from the
  brief: `engine/backends/base.py` (`get_backend`, `UnsupportedInputError`
  with `format`/`mime`/`supported`), `PypdfiumPdfBackend` and
  `PillowImageBackend`, and the deprecated alias
  `engine/preprocessing/io.py:_from_pdf(path, sha256, dpi)` which delegates to
  `PypdfiumPdfBackend.load()`. Test 4 uses that real alias.
- The 2-page PDF fixture is built in-test with Pillow's multi-page PDF save
  (`save_all=True`), the same in-test idiom `tests/test_ocr.py` uses for
  image-only PDFs; pypdfium2 rasterizes both pages, so the byte-identical
  comparison exercises the real render path.
- No other file was modified this round; `uv.lock` untouched; no secrets.

## Checks

- No test commands were run this round (they depend on the new test file, which
  the guard forbids creating). Ruff/mypy on the unchanged tree were not run
  either — no gate depends on them in this tests-only round.

## Test file for the liaison to place at `tests/test_backends.py`

```python
"""D2 tests: input backend registry (engine/backends)."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from engine.backends import (
    PillowImageBackend,
    PypdfiumPdfBackend,
    UnsupportedInputError,
    get_backend,
)
from engine.preprocessing.io import _from_pdf, _sha256_of


def _write_two_page_pdf(path: Path) -> None:
    first = Image.new("RGB", (200, 100), "white")
    second = Image.new("RGB", (150, 120), "white")
    first.save(path, "PDF", save_all=True, append_images=[second])


def test_pdf_resolves_to_pypdfium_backend():
    assert isinstance(get_backend(Path("x.pdf")), PypdfiumPdfBackend)


def test_image_extensions_resolve_to_pillow_backend():
    for suffix in (".png", ".jpg", ".webp"):
        assert isinstance(get_backend(Path(f"x{suffix}")), PillowImageBackend)


def test_unsupported_format_raises_structured_error():
    with pytest.raises(UnsupportedInputError) as excinfo:
        get_backend(Path("x.docx"))
    assert excinfo.value.format == ".docx"
    assert excinfo.value.supported


def test_old_and_new_pdf_paths_give_identical_loads(tmp_path):
    """The deprecated _from_pdf() alias and the registry path agree byte for byte."""
    pdf = tmp_path / "two.pdf"
    _write_two_page_pdf(pdf)
    sha256 = _sha256_of(pdf)
    old = _from_pdf(pdf, sha256, 150)
    new = get_backend(pdf).load(pdf, dpi=150)
    assert [p.page for p in old] == [0, 1]
    assert [p.page for p in new] == [0, 1]
    assert [p.sha256 for p in old] == [sha256] * 2
    assert [p.sha256 for p in new] == [sha256] * 2
    for a, b in zip(old, new):
        assert a.data.shape == b.data.shape
        assert a.data.tobytes() == b.data.tobytes()


def test_pagination_and_page_count(tmp_path):
    pdf_backend = PypdfiumPdfBackend()
    image_backend = PillowImageBackend()
    assert pdf_backend.supports_pagination() is True
    assert image_backend.supports_pagination() is False
    pdf = tmp_path / "two.pdf"
    _write_two_page_pdf(pdf)
    assert pdf_backend.page_count(pdf) == 2
    png = tmp_path / "one.png"
    Image.new("RGB", (60, 40), "white").save(png, "PNG")
    assert image_backend.page_count(png) == 1
```

## Liaison verification (26/11, after placing the test file)
- Extracted the fenced block verbatim into `tests/test_backends.py` (5 tests).
- `pytest tests/test_backends.py`: 5 passed, exit 0.
- Full suite: **179 tests, 0 failures** (junitxml count, liaison run).
- `lv3.sh verify`: pytest 0, validate 35 passed, ruff clean, mypy 0 errors
  (79 source files), validation eval F1 0.8, industrial eval routing 1.0 /
  F1 0.933 / unit 0.875.
