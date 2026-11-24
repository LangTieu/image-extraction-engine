"""Append-only audit trail (P5 item 8).

Every human decision (accept / correct / reject) and every corrected result
version is recorded. Entries are immutable: the repository only supports
append and read. Corrected ExtractionResults are versioned as JSON files.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel


class AuditEntry(BaseModel):
    entry_id: str
    timestamp: str  # UTC ISO-8601
    who: str
    action: str  # accept | correct | reject | version
    field_name: str | None = None
    table_name: str | None = None
    row_index: int | None = None
    col_index: int | None = None
    old_value: Any = None
    new_value: Any = None
    reason: str | None = None
    result_ref: str | None = None


class AuditRepository(Protocol):
    def append(self, entry: AuditEntry) -> None: ...

    def list_entries(self) -> list[AuditEntry]: ...


class FileAuditRepository:
    """JSONL append-only file; one JSON object per line."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, entry: AuditEntry) -> None:
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry.model_dump(), ensure_ascii=False) + "\n")

    def list_entries(self) -> list[AuditEntry]:
        if not self.path.exists():
            return []
        entries: list[AuditEntry] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                entries.append(AuditEntry.model_validate_json(line))
        return entries


class ResultVersionStore:
    """Keeps every corrected ExtractionResult as an immutable JSON version."""

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def save(self, result_json: dict[str, Any], who: str, reason: str | None = None) -> str:
        """Write result_versions/<ts>_<n>.json; returns the version file ref."""
        n = len(list(self.directory.glob("*.json"))) + 1
        ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        name = f"{ts}_v{n:04d}.json"
        path = self.directory / name
        payload = {
            "version_ref": name,
            "saved_at": datetime.now(UTC).isoformat(),
            "saved_by": who,
            "reason": reason,
            "result": result_json,
        }
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return name

    def list_versions(self) -> list[str]:
        return sorted(p.name for p in self.directory.glob("*.json"))

    def load(self, name: str) -> dict[str, Any]:
        return json.loads((self.directory / name).read_text(encoding="utf-8"))
