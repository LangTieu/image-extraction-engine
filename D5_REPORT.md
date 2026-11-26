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
    The first version only *claimed* this — nothing dropped a node whose prov
    carried pages from more than one page. Fixed in the fix round: every
    emission site (`text_block`, `table_row`, cell, `field`) now runs a
    `_single_page(prov)` guard and silently skips a multi-page node.
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
  `<stem>.json`). The 422 message now reads
  `fmt must be one of xlsx|csv|json|pdf|chunks_jsonl` (it still named only the
  four old formats after chunks_jsonl was wired in).

## Fix round (this commit): what was broken and what changed

- **Single-page enforcement was missing.** `build_chunks` emitted every node
  regardless of whether its `prov` covered more than one page. Fixed with
  `_single_page()` guards at all four emission sites in
  `engine/export/chunks.py`.
- **Two tests failed against the seed fixture (6 passed, 2 failed before the
  fix).** Both assumed every seed node carries provenance; the seed is a
  pre-D1 fixture with `prov: null` everywhere, so seed-derived chunks
  legitimately have empty `prov`:
  - `test_order_and_metadata_present`: removed the blanket
    `assert chunk["prov"]`; kept order/metadata-shape assertions, added a
    seed-flavour prov check (all seed chunks have `prov == []`) plus a
    synthetic prov-bearing block that must surface its prov in its chunk.
  - `test_no_chunk_spans_two_pages`: `pages == {1}` became "a prov-bearing
    chunk sits on exactly one page"; added a synthetic two-page block that
    must be dropped while a single-page sibling is kept.

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

## Live smoke (port 3011) — re-run in the fix round

- Started `uvicorn service.api.app:app` on `127.0.0.1:3011`.
- Seed PNGs (`coil_table_001` etc.) complete but produce empty artifacts:
  `detect_glare` reports glare_ratio 1.0 on every seed image (white
  synthetics), the pipeline blanks the frame and yields 0 blocks / 0 tables /
  0 fields → 0 chunks. Pre-existing engine behaviour, unchanged by this
  branch; `GET .../exports/chunks_jsonl` still returns 200 with a 0-byte
  NDJSON body.
- To prove a non-empty path end-to-end, a rendered PNG with dark background
  and two text lines was uploaded: 202 → `completed` → download 200 with a
  584-byte `smoke_dark.chunks_jsonl` containing 2 `text_block` chunks
  (`order` 0..1, each `prov` on one page), e.g.
  `{"chunk_id":"4071479e732269f8","order":0,"kind":"text_block","text":"Batch record 42"}`.
- `GET .../exports/bogus` → 422 with the corrected message
  `fmt must be one of xlsx|csv|json|pdf|chunks_jsonl`.
- Also verified in-process earlier: a coil-table ground-truth result yields
  10 chunks (kinds `text_block`, `table_row`, `field`; coil ids `H00001`,
  `H00002`) and byte-identical output across two runs.

## Gates (exit codes) — re-run in the fix round

```
.venv/bin/python -m pytest -q                     exit=0  (244 passed)
python -m benchmark.validate benchmark/seed       exit=0  (35 passed)
ruff check .                                      exit=0
mypy engine benchmark service tests               exit=0  (108 source files)
```

## Tests: tests/test_chunks.py — ON BRANCH, 8 PASSED

`tests/test_chunks.py` is now on the branch (placed in the fix round after
the first round could not create it) and passes 8/8. The two tests the first
round got wrong are repaired as described above; the rest is unchanged from
the block below.

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
- The seed PNGs' 100% glare reading is a pre-existing preprocessing
  characteristic of white-background synthetic fixtures, not a defect of this
  branch; the non-empty live path was proven with a rendered dark image.
- `service/api/app.py` was edited (outside the engine, inside the smoke path)
  to let the new format download and to correct the 422 message; flagged here
  per the brief.
