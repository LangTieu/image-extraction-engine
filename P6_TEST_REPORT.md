# P6 TEST REPORT — tests/test_export.py could not be written (guard blocked)

**guard chặn Write trực tiếp — liaison đặt file vào tests/test_export.py giúp**

Status: `Write` of `tests/test_export.py` was denied once more this round by the
same filename-level approval guard ("Add a new test file … The user did not ask
for this"), even though the user (Henrry) explicitly requested this file in the
brief. Per the brief's no-retry rule, work stopped after that single denial.
Below is the complete, ready-to-run file content; dropping it verbatim into
`tests/test_export.py` and running the three checks in the brief is all that
remains.

Checks actually run this round: none beyond the reads above (no file was
written into `tests/`, so the pytest/ruff/mypy round from the brief's step 3
was not reached — the brief only runs them after a successful Write).

## How to finish (liaison)

1. Save the fenced block below as `tests/test_export.py`.
2. Run, reading real exit codes, no pipes:
   - `.venv/bin/python -m pytest tests/ -q` (must pass all existing 102 + these)
   - `.venv/bin/ruff check engine/ tests/`
   - `.venv/bin/mypy engine benchmark tests`
3. No production code is touched by these tests; if any fails, that is a real
   finding, not a test artifact (except where noted in the block's comments).

Notes on the content, section by section (bug each test pins):

1. Determinism — old openpyxl bug: workbook zip entries/dcterms:modified
   stamped with now(). Exports twice ≥1.1 s apart, compares sha256, per format.
2. `_as_number` — old bug: float() accepted `nan`/`inf`/`1e3` and split
   whitespace thousands; now junk stays text, real numbers and vi-style
   thousands dots (`"1.234"` with decimal="," → 1234) parse.
3. Batch — old bug: duplicate stems silently overwrote; secondary sidecars
   could be untracked. Checks `dup.csv`/`dup_2.csv`, checksum-vs-disk for every
   manifest entry, sidecars inside `bundle.zip`.
4. JSON schema — old bug: cwd-dependent schema path; unreadable schema fell
   back silently. cwd test + garbage-schema `ExportError` test (clears the
   `lru_cache` so the patched path is actually read).
5. Cells beat rows — old bug: exporters used stale `rows`. CSV text and
   Flate-decompressed PDF streams must contain the live `H99999`, never the
   stale `H00001`.
6. Preview/XLSX fills — old bug: fills could land on header/footer; preview
   skipped unknown-confidence cells. Checks a red pixel on the bbox border and
   the fill on spreadsheet row 2 (first data row), not row 1, not the footer.
7. bundle.zip — in-zip manifest vs on-disk manifest (bundle checksum absent in
   zip), per-member checksums, fixed 1980-01-01 member timestamps.
8. `values_only` — old bug: extensions/validation leaked. Asserts none of the
   provenance keys appear anywhere in the output.
9. Registry — duplicate `register()` must raise `ValueError`, not replace.
10. reportlab absent — old bug: one missing backend killed `import
    engine.export` and CSV/JSON/XLSX with it. Subprocess blocks the reportlab
    import, imports the package, exports CSV, expects PDF `ExportError`.

```python
"""P6 test round: tests for engine/export, one section per reviewed bug.

Sections (brief mlai_p6_test_brief.md):
1. byte determinism for csv/json/xlsx/jpg/pdf across a >=1.1s gap
2. _as_number junk rejection + vi-style thousands
3. batch: duplicate stems, multi-table sidecars, zip manifest consistency
4. JSON schema: cwd independence, garbage schema -> ExportError
5. cells beat rows (CSV + PDF)
6. preview red pixels + XLSX fill row placement
7. bundle.zip consistency and fixed member timestamps
8. values_only strips provenance/extensions
9. duplicate register() raises ValueError
10. reportlab absent: import engine.export still works, PDF raises ExportError
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import time
import zipfile
import zlib
from pathlib import Path

import pytest

from engine.export.base import ExportError, ExportOptions, get_exporter, register
from engine.export.batch import export_batch
from engine.export.json_export import _schema
from engine.export.xlsx import _as_number
from engine.schema.models import BBox, Cell, ExtractionResult

REPO = Path(__file__).resolve().parent.parent
SEED = REPO / "benchmark" / "seed" / "coil_table" / "ground_truth" / "coil_table_001.png.json"


def load_result() -> ExtractionResult:
    return ExtractionResult.model_validate_json(SEED.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def white_image(directory: Path, name: str = "coil_table_001.png", size=(200, 100)):
    from PIL import Image

    p = directory / name
    Image.new("RGB", size, "white").save(p)
    return p


# --- 1. Determinism ----------------------------------------------------------


@pytest.mark.parametrize("fmt,suffix", [
    ("csv", ".csv"),
    ("json", ".json"),
    ("xlsx", ".xlsx"),
    ("jpg", ".jpg"),
    ("pdf", ".pdf"),
])
def test_deterministic_bytes(tmp_path, fmt: str, suffix: str):
    """Same result exported twice, >=1.1s apart, must give identical bytes.

    Catches the old openpyxl bug (workbook zip entries stamped with now()).
    """
    result = load_result()
    white_image(tmp_path)
    opts = ExportOptions(image_dir=tmp_path)

    def run(tag: str) -> Path:
        out = tmp_path / f"{tag}{suffix}"
        get_exporter(fmt).export(result, out, opts)
        return out

    first = run("first")
    time.sleep(1.1)
    second = run("second")
    assert sha256(first) == sha256(second), f"{fmt} export is not byte-deterministic"


# --- 2. _as_number -----------------------------------------------------------


@pytest.mark.parametrize("junk", ["nan", "NaN", "inf", "-inf", "Inf", "1e3", "1E3", "12 500"])
def test_as_number_rejects_junk(junk):
    is_num, value, _fmt = _as_number(junk, ".")
    assert is_num is False and value is None


@pytest.mark.parametrize(
    "text,decimal,expected",
    [
        ("123", ".", 123),
        ("1.20", ".", 1.20),
        ("-5", ".", -5),
        ("0.80", ".", 0.80),
        ("12,5", ",", 12.5),
        ("1.234", ",", 1234),  # vi-style thousands dot, not a decimal point
        ("1.234.567", ",", 1234567),
    ],
)
def test_as_number_accepts_real_numbers(text, decimal, expected):
    is_num, value, _fmt = _as_number(text, decimal)
    assert is_num is True and value == expected


# --- 3. Batch ----------------------------------------------------------------


def test_batch_duplicate_stem_keeps_both(tmp_path):
    """Two results with the same stem must not overwrite each other."""
    a = load_result().model_copy(deep=True)
    b = load_result().model_copy(deep=True)
    for r in (a, b):
        r.source.file_name = "dup.png"
    manifest = export_batch([a, b], tmp_path, formats=["csv"])
    csv_names = [f["path"] for f in manifest["files"] if f["path"].endswith(".csv")]
    assert "dup.csv" in csv_names and "dup_2.csv" in csv_names
    for entry in manifest["files"]:
        on_disk = tmp_path / entry["path"]
        assert on_disk.is_file(), f"manifest references missing file {entry['path']}"
        assert entry["sha256"] == sha256(on_disk)


def test_batch_sidecars_and_zip_manifest(tmp_path):
    """Every file on disk (primary, .tableN.csv and _meta.csv sidecars) is in
    the manifest with the right checksum and inside bundle.zip."""
    result = load_result()
    second = result.tables[0].model_copy(deep=True)
    second.table_name = "table2"
    result.tables.append(second)
    manifest = export_batch(
        [result],
        tmp_path,
        formats=["csv"],
        options=ExportOptions(csv_meta_sidecar=True, zip_bundle=True),
    )
    written = {p.name for p in tmp_path.iterdir() if p.suffix in {".csv", ".json"}}
    tracked = {f["path"] for f in manifest["files"]}
    assert "coil_table_001.table2.csv" in written
    assert "coil_table_001_meta.csv" in written
    assert written <= tracked, f"untracked files on disk: {written - tracked}"
    for entry in manifest["files"]:
        assert entry["sha256"] == sha256(tmp_path / entry["path"])
    with zipfile.ZipFile(tmp_path / "bundle.zip") as zf:
        assert set(written) <= set(zf.namelist())


# --- 4. JSON schema ----------------------------------------------------------


def test_json_schema_ignores_cwd(tmp_path, monkeypatch):
    """Exporting from another working directory still validates against the
    repo schema (SCHEMA_PATH is anchored to the repo, not the cwd)."""
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "out.json"
    get_exporter("json").export(load_result(), out, ExportOptions())
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["source"]["file_name"] == "coil_table_001.png"


def test_json_garbage_schema_raises(tmp_path, monkeypatch):
    """A schema file that exists but is unreadable must raise ExportError —
    no silent fallback to the generated schema."""
    bad = tmp_path / "schema_v0.json"
    bad.write_text("{ this is not json", encoding="utf-8")
    monkeypatch.setattr("engine.export.json_export.SCHEMA_PATH", bad)
    _schema.cache_clear()
    try:
        with pytest.raises(ExportError, match="unreadable"):
            get_exporter("json").export(load_result(), tmp_path / "out.json", ExportOptions())
    finally:
        _schema.cache_clear()


# --- 5. Cells beat rows ------------------------------------------------------


def _cells_over_rows_result():
    result = load_result()
    table = result.tables[0]
    table.rows = [["ZA", "H00001", "C00001", "1.20", "1250", "15000", "620", "SPHC"]]
    table.columns = [
        "ZONE", "HOT_COIL_NO", "COLD_COIL_NO", "THICK",
        "WIDTH", "WEIGHT", "LENGTH", "PRODUCT_CODE",
    ]
    live = Cell(row_index=0, col_index=1, text="H99999", confidence=0.5, needs_review=True)
    table.cells = [live]
    return result


def test_cells_beat_rows_csv(tmp_path):
    out = tmp_path / "out.csv"
    get_exporter("csv").export(_cells_over_rows_result(), out, ExportOptions())
    text = out.read_text(encoding="utf-8")
    assert "H99999" in text
    assert "H00001" not in text


def test_cells_beat_rows_pdf(tmp_path):
    out = tmp_path / "out.pdf"
    get_exporter("pdf").export(_cells_over_rows_result(), out, ExportOptions())
    data = out.read_bytes()
    # PDF content streams are Flate-compressed: decompress every stream and
    # search there (raw bytes alone would miss the text).
    text = ""
    for m in re.finditer(rb"stream\r?\n(.*?)endstream", data, re.DOTALL):
        try:
            text += zlib.decompress(m.group(1)).decode("latin-1", "ignore")
        except zlib.error:
            text += m.group(1).decode("latin-1", "ignore")
    assert "H99999" in text
    assert "H00001" not in text


# --- 6. Preview + XLSX fills -------------------------------------------------


def test_preview_draws_red_bbox_for_unknown_confidence(tmp_path):
    from PIL import Image

    result = load_result()
    white_image(tmp_path)
    table = result.tables[0]
    table.cells = [
        Cell(row_index=0, col_index=0, text="X", confidence=None, needs_review=True,
             bbox=BBox(x0=10, y0=10, x1=60, y1=40))
    ]
    out = tmp_path / "preview.png"
    get_exporter("jpg").export(result, out, ExportOptions(image_dir=tmp_path))
    img = Image.open(out).convert("RGB")
    assert img.getpixel((11, 11)) == (220, 50, 50)  # red border pixel on the bbox


def test_xlsx_fill_lands_on_first_data_row(tmp_path):
    from openpyxl import load_workbook

    result = load_result()
    table = result.tables[0]
    assert table.columns and len(table.rows) == 2
    table.cells = [Cell(row_index=0, col_index=1, text="H99999", confidence=0.5, needs_review=True)]
    out = tmp_path / "out.xlsx"
    get_exporter("xlsx").export(result, out, ExportOptions())
    ws = load_workbook(out)[table.table_name]
    filled = ws.cell(row=2, column=2)  # row_index=0 -> first data row (header is row 1)
    assert filled.fill.start_color.rgb in {"00FFC7CE", "FFFFC7CE"}
    assert ws.cell(row=1, column=2).fill.patternType is None  # header untouched
    footer_row = ws.max_row  # footer block untouched
    assert ws.cell(row=footer_row, column=2).fill.patternType is None


# --- 7. bundle.zip -----------------------------------------------------------


def test_bundle_zip_consistency(tmp_path):
    manifest = export_batch(
        [load_result()], tmp_path, formats=["csv"], options=ExportOptions(zip_bundle=True)
    )
    disk_manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    with zipfile.ZipFile(tmp_path / "bundle.zip") as zf:
        in_zip = json.loads(zf.read("manifest.json").decode("utf-8"))
        for info in zf.infolist():
            assert info.date_time == (1980, 1, 1, 0, 0, 0), info.filename
            if info.filename != "manifest.json":
                digest = hashlib.sha256(zf.read(info.filename)).hexdigest()
                assert any(
                    f["path"] == info.filename and f["sha256"] == digest
                    for f in in_zip["files"]
                )
    # in-zip manifest == on-disk manifest minus the bundle's own checksum
    assert in_zip["files"] == disk_manifest["files"]
    assert in_zip["bundle"] == {"name": "bundle.zip"}
    assert disk_manifest["bundle"]["sha256"] == sha256(tmp_path / "bundle.zip")


# --- 8. values_only ----------------------------------------------------------


def test_values_only_strips_extensions(tmp_path):
    result = load_result()
    result.extensions = {
        "validation": {"passed": True},
        "review_item_ids": ["t1", "f2"],
    }
    out = tmp_path / "values.json"
    get_exporter("json").export(result, out, ExportOptions(values_only=True))
    text = out.read_text(encoding="utf-8")
    for key in ("extensions", "validation", "review_item_ids", "bbox", "cells"):
        assert f'"{key}"' not in text, f"values_only output still contains {key!r}"


# --- 9. Registry -------------------------------------------------------------


def test_duplicate_register_raises():
    with pytest.raises(ValueError, match="already registered"):
        register("csv", lambda: get_exporter("csv"))


# --- 10. reportlab absent ----------------------------------------------------


_REPORTLAB_MISSING_SCRIPT = """
import builtins, sys

real_import = builtins.__import__

def blocked(name, *args, **kwargs):
    if name.startswith("reportlab"):
        raise ImportError("reportlab blocked by test")
    return real_import(name, *args, **kwargs)

builtins.__import__ = blocked

import engine.export  # must not raise ModuleNotFoundError
from engine.export.base import ExportError, ExportOptions, get_exporter
from engine.schema.models import ExtractionResult

result = ExtractionResult.model_validate_json(open(sys.argv[1], "rb").read())
get_exporter("csv").export(result, sys.argv[2] + "/out.csv", ExportOptions())
try:
    get_exporter("pdf").export(result, sys.argv[2] + "/out.pdf", ExportOptions())
except ExportError as exc:
    print("OK:", exc)
    sys.exit(0)
print("FAIL: pdf export did not raise ExportError")
sys.exit(1)
"""


def test_reportlab_missing_does_not_break_other_formats(tmp_path):
    """With reportlab unimportable, `import engine.export` still works, CSV
    still exports, and PDF export raises the typed ExportError."""
    proc = subprocess.run(
        [sys.executable, "-c", _REPORTLAB_MISSING_SCRIPT, str(SEED), str(tmp_path)],
        capture_output=True, text=True, cwd=REPO,
    )
    assert (tmp_path / "out.csv").is_file()
    assert proc.returncode == 0, f"stdout={proc.stdout}\nstderr={proc.stderr}"
    assert proc.stdout.startswith("OK:")
```
