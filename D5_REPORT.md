# D5 REPORT — RAG chunk writer and basic typing (branch `d5-chunk-typing`)

## What shipped

- `engine/export/chunks.py` — the `chunks_jsonl` NDJSON exporter plus
  `build_chunks(result, options)` and `normalize_text()`:
  - One JSON line per chunk. Chunk kinds: `text_block`, `table_row`, `field`.
  - `chunk_id` = first 16 hex chars of
    `sha256(f"{source_sha256}:{page}:{kind}:{order}:{normalized_text}")`,
    where `normalized_text` collapses whitespace runs to single spaces and
    strips (OCR line-break noise cannot change the id). Computed from the
    *uncapped* text so a larger `chunk_max_chars` never silently changes ids
    for unchanged content.
  - Chunks never span pages: a chunk's `prov` entries are all from one page.
  - Table rows stay separate chunks (one row = one chunk, joined with `" | "`),
    never merged across rows; rows with different coil IDs (`HOT_COIL_NO`,
    `COLD_COIL_NO`, `COIL_ID` column or field name) therefore never share a
    chunk, and each such chunk carries `coil_id` + `row_index` + `table_name`.
  - Reading order is a dense 0..n-1 `order` (text blocks in `reading_order`
    order, then table rows, then fields).
  - `prov` entries round-trip into `engine.schema.models.Provenance`.
  - `ExportOptions.chunk_max_chars` (default 1200) hard-caps `text`.
  - Deterministic: same result + options → same bytes.
- `engine/export/__init__.py` — registered as `chunks_jsonl`.
- `engine/export/base.py` — added `ExportOptions.chunk_max_chars: int = 1200`.
- `engine/py.typed` (PEP 561 marker) and `[tool.setuptools.package-data]`
  `engine = ["py.typed"]` in `pyproject.toml`.
- `service/api/app.py` — the download route
  `GET /v1/jobs/{id}/exports/{fmt}` accepted only `xlsx|csv|json|pdf`; it now
  also accepts `chunks_jsonl` (artifact file is `<stem>.chunks_jsonl` because
  `export_batch` names files `<stem>.<format>`; download name maps it to
  `<stem>.json`).

## Typing: ignore reduction

- N0 (baseline on `main`, `2cda31b`) = **1**: the D1–D4 rounds already removed
  the groups this brief names (`lazy torch/vLLM imports`, `psd-tools`,
  `reportlab`, `pytesseract`, `dict access in review store` were done in D1–D4
  and their ignores are gone from main). The only remaining one was
  `engine/validation/review.py:217` — `# type: ignore[union-attr]` on
  `json.loads(self.store_path.read_text(...))`.
- Fix: bind `store = self.store_path` and `if store is None: return` before
  use. N1 = **0** ≤ 0.8 × N0 = 0.8. No new ignores were added anywhere; a
  repo-wide scan after the change finds zero `type: ignore` in `engine/`.

## Live smoke (port 3011)

- Started `uvicorn service.api.app:app` on `127.0.0.1:3011` with a throwaway
  API key exported only into that process's environment (not stored in the
  repo).
- `POST /v1/jobs?export_formats=chunks_jsonl` with a PNG → 202
  (`job_ac66ed86f145`), job reached `completed`, then
  `GET /v1/jobs/job_ac66ed86f145/exports/chunks_jsonl?file_id=...` → **200**
  with the artifact metadata (`coil_table_001.chunks_jsonl`, mime
  `application/x-ndjson`).
- The artifact body is empty for these uploads because the extractor found no
  text/tables/fields in them (verified directly: the stored `result_json` has
  0 text blocks, 0 tables, 0 fields → 0 chunks, and the checksum equals
  sha256 of the empty string). The first live attempt exposed two real wiring
  bugs, both fixed above: the download route's format allow-list, and the
  exporter rejecting `export_batch`'s `<stem>.chunks_jsonl` file name (404/422
  in the first two runs). Also verified in-process earlier: a coil-table
  ground-truth result yields 10 chunks (kinds `text_block`, `table_row`,
  `field`; coil ids `H00001`, `H00002`) and byte-identical output across two
  runs.

## Gates (exit codes)

```
pytest -q                                       exit=0
python -m benchmark.validate benchmark/seed     exit=0
ruff check .                                    exit=0
mypy engine benchmark service tests             exit=0  (107 source files)
```

## Tests: tests/test_chunks.py — PLACE ON BRANCH FROM THE BLOCK BELOW

The environment blocked creating `tests/test_chunks.py` (new test files need
an explicit ask). The full round is below; place it verbatim, then run
`.venv/bin/python -m pytest -q` (expect 8 new tests, all passing — the
assertions were validated against the implementation inline during this run).

```python
"""D5 test round: the chunks_jsonl RAG chunk exporter (tests/test_chunks.py)."""

from __future__ import annotations

import json
from pathlib import Path

from engine.export.base import ExportOptions, ExportError, get_exporter
from engine.export.chunks import build_chunks, normalize_text
from engine.schema.models import (
    BBox,
    ExtractionResult,
    Provenance,
    TextBlock,
)

REPO = Path(__file__).resolve().parent.parent
SEED = REPO / "benchmark" / "seed" / "coil_table" / "ground_truth" / "coil_table_001.png.json"


def load_result() -> ExtractionResult:
    return ExtractionResult.model_validate_json(SEED.read_text(encoding="utf-8"))


def page_prov(page: int) -> Provenance:
    return Provenance(page=page, bbox=BBox(x0=0, y0=0, x1=10, y1=10))


# --- 1. Reading order + metadata completeness --------------------------------


def test_order_and_metadata_present():
    result = load_result()
    chunks = build_chunks(result)
    assert [c["order"] for c in chunks] == list(range(len(chunks))), "order must be 0..n-1"
    for chunk in chunks:
        assert chunk["kind"] in ("text_block", "table_row", "field")
        assert set(chunk) >= {"chunk_id", "text", "order", "kind", "source", "prov"}
        assert set(chunk["source"]) == {"file_name", "sha256"}
        assert len(chunk["chunk_id"]) == 16 and int(chunk["chunk_id"], 16) >= 0
        assert chunk["prov"]
    kinds = {c["kind"] for c in chunks}
    assert kinds >= {"table_row"}, f"seed should yield table_row chunks, got {kinds}"


# --- 2. No chunk spans two pages ---------------------------------------------


def test_no_chunk_spans_two_pages():
    result = load_result()
    for chunk in build_chunks(result):
        pages = {p["page"] for p in chunk["prov"]}
        assert pages == {1}, f"chunk {chunk['chunk_id']} spans pages {pages}"
    mixed = load_result()
    mixed.text_blocks.append(TextBlock(text="two page", prov=[page_prov(1), page_prov(2)]))
    for chunk in build_chunks(mixed):
        assert chunk["text"] != "two page", "chunk with prov on 2 pages was emitted"


# --- 3. Rows with different coil IDs are never merged -------------------------


def test_rows_with_different_coil_ids_not_merged():
    result = load_result()
    table = result.tables[0]
    table.columns = ["HOT_COIL_NO", "WEIGHT"]
    table.rows = [["H26-0001", "10.5"], ["H26-0002", "11.0"]]
    row_chunks = [c for c in build_chunks(result) if c["kind"] == "table_row"]
    assert [c.get("coil_id") for c in row_chunks] == ["H26-0001", "H26-0002"]
    texts = [c["text"] for c in row_chunks]
    assert not any("H26-0001" in t and "H26-0002" in t for t in texts)


# --- 4. Every line parses; IDs identical across two runs ----------------------


def test_jsonl_lines_parse_and_ids_stable(tmp_path):
    result = load_result()
    exporter = get_exporter("chunks_jsonl")
    first, second = tmp_path / "a.jsonl", tmp_path / "b.ndjson"
    exporter.export(result, first, ExportOptions())
    exporter.export(result, second, ExportOptions())
    lines_a = first.read_text(encoding="utf-8").splitlines()
    assert lines_a and lines_a == second.read_text(encoding="utf-8").splitlines()
    for line in lines_a:
        assert json.loads(line)["chunk_id"]


def test_unknown_suffix_rejected(tmp_path):
    try:
        get_exporter("chunks_jsonl").export(load_result(), tmp_path / "x.txt", ExportOptions())
    except ExportError:
        pass
    else:
        raise AssertionError("expected ExportError for non-jsonl suffix")


# --- 5. prov round-trips into Provenance --------------------------------------


def test_prov_round_trips():
    for chunk in build_chunks(load_result()):
        for raw in chunk["prov"]:
            assert Provenance.model_validate(raw).model_dump(mode="json") == raw


def test_chunk_max_chars_caps_text():
    result = load_result()
    result.text_blocks = [TextBlock(text="x" * 5000, reading_order=0, prov=[page_prov(1)])]
    assert len(build_chunks(result, ExportOptions(chunk_max_chars=1200))[0]["text"]) == 1200
    assert len(build_chunks(result, ExportOptions(chunk_max_chars=7))[0]["text"]) == 7


def test_normalize_text():
    assert normalize_text("  a \n b\tc  ") == "a b c"
```

## Assumptions

- The brief's named ignore groups were already gone from `main` (removed in
  D1–D4); N0 = 1 comes from the remaining review-store ignore, removed here.
- The live-smoke artifact being empty reflects blank seed fixtures, not a
  defect; chunk content was proven from a real ground-truth result in-process.
- `service/api/app.py` was edited (outside the engine, inside the smoke path)
  to let the new format download; flagged here per the brief.
