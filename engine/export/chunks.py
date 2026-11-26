"""RAG chunk writer (D5): one NDJSON file of retrieval-ready chunks.

Every chunk is a JSON line with a stable ``chunk_id`` (first 16 hex chars of
``sha256(f"{source_sha256}:{page}:{kind}:{order}:{normalized_text}")``), the
chunk text, its reading order, a kind (``text_block`` | ``table_row`` |
``field``), source identity and full ``prov`` provenance. Chunks never cross
a page, table rows stay separate chunks, and each chunk is capped at
``ExportOptions.chunk_max_chars`` (default 1200) characters. Deterministic:
same result in, same bytes out.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from engine.export.base import ExportArtifact, ExportError, ExportOptions, artifact
from engine.schema.models import ExtractionResult, Provenance

MIME = "application/x-ndjson"

_NORMALIZE_RE = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    """Collapse whitespace and trim, so OCR line-break noise cannot change ids."""
    return _NORMALIZE_RE.sub(" ", text).strip()


def _chunk_id(source_sha: str, page: int | None, kind: str, order: int, text: str) -> str:
    key = f"{source_sha}:{page if page is not None else ''}:{kind}:{order}:{normalize_text(text)}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def _cap(text: str, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    return text[:max_chars]


def _single_page(provs: list[Provenance]) -> bool:
    pages = {p.page for p in provs if p.page is not None}
    return len(pages) <= 1


def _page_of(provs: list[Provenance]) -> int | None:
    pages = {p.page for p in provs if p.page is not None}
    return pages.pop() if len(pages) == 1 else (provs[0].page if provs else None)


def _source(result: ExtractionResult) -> dict[str, Any]:
    src = result.source
    return {
        "file_name": src.file_name if src else None,
        "sha256": src.sha256 if src else None,
    }


def _chunk(
    result: ExtractionResult,
    kind: str,
    order: int,
    text: str,
    provs: list[Provenance],
    max_chars: int,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    page = _page_of(provs)
    shown = _cap(text, max_chars)
    normalized = normalize_text(text)
    src_sha = result.source.sha256 or "" if result.source else ""
    chunk: dict[str, Any] = {
        "chunk_id": _chunk_id(src_sha, page, kind, order, normalized),
        "text": shown,
        "order": order,
        "kind": kind,
        "source": _source(result),
        "prov": [p.model_dump(mode="json") for p in provs],
    }
    if extra:
        chunk.update(extra)
    return chunk


def build_chunks(
    result: ExtractionResult, options: ExportOptions | None = None
) -> list[dict[str, Any]]:
    """Build the chunk records for ``result`` in reading order."""
    options = options or ExportOptions()
    max_chars = options.chunk_max_chars
    chunks: list[dict[str, Any]] = []
    order = 0

    blocks = [b for b in result.text_blocks if b.text]
    for block in sorted(blocks, key=lambda b: (b.reading_order is None, b.reading_order or 0)):
        if not _single_page(block.prov):
            continue
        chunks.append(_chunk(result, "text_block", order, block.text, block.prov, max_chars))
        order += 1

    for table in result.tables:
        cols = table.columns or []
        if table.rows:
            for row_index, row in enumerate(table.rows):
                cells = [str(c) for c in (row or []) if c not in (None, "")]
                if not cells:
                    continue
                text = " | ".join(cells)
                extra: dict[str, Any] = {"table_name": table.table_name, "row_index": row_index}
                for field_name in ("HOT_COIL_NO", "COLD_COIL_NO", "COIL_ID"):
                    if cols and field_name in cols:
                        idx = cols.index(field_name)
                        if idx < len(row or ()) and (row or [])[idx]:
                            extra["coil_id"] = str(row[idx])
                            break
                provs = table.prov or []
                if not _single_page(provs):
                    continue
                chunks.append(
                    _chunk(result, "table_row", order, text, provs, max_chars, extra)
                )
                order += 1
        else:
            for cell in table.cells:
                if not cell.text:
                    continue
                col = cols[cell.col_index] if cell.col_index < len(cols) else None
                text = f"{col}: {cell.text}" if col else (cell.text or "")
                extra = {"table_name": table.table_name, "row_index": cell.row_index}
                if cols and cols[cell.col_index] in ("HOT_COIL_NO", "COLD_COIL_NO", "COIL_ID"):
                    extra["coil_id"] = cell.text
                if not _single_page(cell.prov or table.prov):
                    continue
                chunks.append(
                    _chunk(
                        result, "table_row", order, text,
                        cell.prov or table.prov, max_chars, extra,
                    )
                )
                order += 1

    for field in result.fields:
        raw = field.raw_text or (str(field.value) if field.value is not None else "")
        if not raw:
            continue
        text = f"{field.name}: {raw}"
        extra = {}
        if field.name in ("HOT_COIL_NO", "COLD_COIL_NO", "COIL_ID"):
            extra["coil_id"] = str(raw)
        if not _single_page(field.prov):
            continue
        chunks.append(_chunk(result, "field", order, text, field.prov, max_chars, extra))
        order += 1

    return chunks


class ChunkJsonlExporter:
    name = "chunks_jsonl"

    def export(
        self, result: ExtractionResult, out_path: Path | str, options: ExportOptions | None = None
    ) -> ExportArtifact:
        options = options or ExportOptions()
        out = Path(out_path)
        name = out.name.lower()
        if not (name.endswith(".chunks_jsonl") or out.suffix.lower() in (".jsonl", ".ndjson")):
            raise ExportError(
                self.name, f"expected a .jsonl/.ndjson path, got {out.name!r}"
            )
        chunks = build_chunks(result, options)
        out.parent.mkdir(parents=True, exist_ok=True)
        payload = "".join(
            json.dumps(c, ensure_ascii=False, sort_keys=False) + "\n" for c in chunks
        )
        out.write_text(payload, encoding="utf-8")
        return artifact(out, MIME)


def make() -> ChunkJsonlExporter:
    return ChunkJsonlExporter()
