"""D5 test round: the chunks_jsonl RAG chunk exporter (tests/test_chunks.py)."""

from __future__ import annotations

import json
from pathlib import Path

from engine.export.base import ExportError, ExportOptions, get_exporter
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
    kinds = {c["kind"] for c in chunks}
    assert kinds >= {"table_row"}, f"seed should yield table_row chunks, got {kinds}"
    # prov fidelity, seed flavour: every seed node has prov null (pre-D1 fixture), so
    # every seed-derived chunk must have empty prov — and a node that DOES carry
    # prov must surface it unchanged in its chunk.
    assert all(c["prov"] == [] for c in chunks), "seed nodes have prov null; chunks must too"
    single = load_result()
    single.text_blocks.append(TextBlock(text="with prov", reading_order=999, prov=[page_prov(1)]))
    match = [c for c in build_chunks(single) if c["text"].startswith("with prov")]
    assert len(match) == 1 and match[0]["prov"], "chunk of a prov-bearing block must have prov"
    expected_prov = page_prov(1).model_dump(mode="json")
    assert match[0]["prov"] == [expected_prov], "chunk prov must equal the block's prov"


# --- 2. No chunk spans two pages ---------------------------------------------


def test_no_chunk_spans_two_pages():
    result = load_result()
    for chunk in build_chunks(result):
        pages = {p["page"] for p in chunk["prov"]}
        # seed is pre-D1 (prov null everywhere), so only prov-bearing chunks
        # are page-checked; a single-prov chunk can only ever sit on one page.
        if pages:
            assert len(pages) == 1, f"chunk {chunk['chunk_id']} spans pages {pages}"
    mixed = load_result()
    mixed.text_blocks.append(TextBlock(text="two page", prov=[page_prov(1), page_prov(2)]))
    mixed.text_blocks.append(TextBlock(text="one page", reading_order=998, prov=[page_prov(1)]))
    texts = [c["text"] for c in build_chunks(mixed)]
    assert "two page" not in " ".join(texts), "chunk with prov on 2 pages was emitted"
    assert any(t.startswith("one page") for t in texts), "single-page chunk was dropped"


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
