"""Human-review backend (P5 item 8).

Review items are created for fields flagged needs_review (below threshold or
with error findings). Actions: accept, correct (re-runs validation on the
corrected result), reject. The queue persists to JSON so a review session can
outlive a process. Every action is appended to the audit trail.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from engine.validation.audit import AuditRepository


@dataclass
class ReviewThresholds:
    """Per-field/profile auto-accept thresholds; configurable without code."""

    default_accept: float = 0.85
    per_field: dict[str, float] = field(default_factory=dict)

    def threshold_for(self, field_name: str, profile_name: str | None = None) -> float:
        key = f"{profile_name}.{field_name}" if profile_name else field_name
        if profile_name and key in self.per_field:
            return self.per_field[key]
        return self.per_field.get(field_name, self.default_accept)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> ReviewThresholds:
        data = data or {}
        return cls(
            default_accept=float(data.get("default_accept", 0.85)),
            per_field={k: float(v) for k, v in (data.get("per_field") or {}).items()},
        )


@dataclass
class ReviewItem:
    item_id: str
    field_name: str
    table_name: str | None
    row_index: int | None
    col_index: int | None
    value: Any
    proposals: list[str]
    confidence: float
    reasons: list[str]
    status: str = "pending"  # pending | accepted | corrected | rejected
    corrected_value: Any | None = None
    reviewed_by: str | None = None
    result_ref: str | None = None  # identifier of the result version

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ReviewItem:
        return cls(**d)


def build_review_items(
    *,
    field_flags: dict[str, dict[str, Any]],
    cell_flags: list[dict[str, Any]],
    thresholds: ReviewThresholds,
    profile_name: str | None = None,
) -> list[ReviewItem]:
    """Create one ReviewItem per flagged field or cell.

    ``field_flags``: name -> {value, proposals, confidence, reasons}.
    ``cell_flags``: {table_name, row_index, col_index, value, confidence, reasons}.
    """
    items: list[ReviewItem] = []
    for name, info in field_flags.items():
        t = thresholds.threshold_for(name, profile_name)
        needs = info.get("needs_review") or info.get("confidence", 1.0) < t
        if not needs:
            continue
        items.append(
            ReviewItem(
                item_id=uuid.uuid4().hex[:12],
                field_name=name,
                table_name=None,
                row_index=None,
                col_index=None,
                value=info.get("value"),
                proposals=list(info.get("proposals") or ()),
                confidence=float(info.get("confidence", 0.0)),
                reasons=list(info.get("reasons") or ()),
                result_ref=info.get("result_ref"),
            )
        )
    for info in cell_flags:
        cname = str(info.get("field_name"))
        t = thresholds.threshold_for(cname, profile_name)
        if not (info.get("needs_review") or info.get("confidence", 1.0) < t):
            continue
        items.append(
            ReviewItem(
                item_id=uuid.uuid4().hex[:12],
                field_name=cname,
                table_name=info.get("table_name"),
                row_index=info.get("row_index"),
                col_index=info.get("col_index"),
                value=info.get("value"),
                proposals=list(info.get("proposals") or ()),
                confidence=float(info.get("confidence", 0.0)),
                reasons=list(info.get("reasons") or ()),
                result_ref=info.get("result_ref"),
            )
        )
    return items


class ReviewBackend:
    """In-memory queue with optional JSON persistence and audit logging."""

    def __init__(
        self,
        store_path: str | Path | None = None,
        audit_repository: AuditRepository | None = None,
    ) -> None:
        self.store_path = Path(store_path) if store_path else None
        self.audit = audit_repository
        self.items: dict[str, ReviewItem] = {}
        # Hook: called after a correction so the caller can re-run validation
        # on the corrected result and append the new version to the audit trail.
        self.on_correct: Any = None
        if self.store_path and self.store_path.exists():
            self._load()

    def list_pending(self, *, max_confidence: float | None = None) -> list[ReviewItem]:
        return sorted(
            (
                i
                for i in self.items.values()
                if i.status == "pending"
                and (max_confidence is None or i.confidence <= max_confidence)
            ),
            key=lambda i: i.confidence,
        )

    def get(self, item_id: str) -> ReviewItem | None:
        return self.items.get(item_id)

    def accept(self, item_id: str, who: str) -> ReviewItem | None:
        return self._close(item_id, "accept", "accepted", who, None, None)

    def reject(self, item_id: str, who: str, reason: str) -> ReviewItem | None:
        return self._close(item_id, "reject", "rejected", who, None, reason)

    def correct(
        self, item_id: str, new_value: Any, who: str, reason: str | None = None
    ) -> ReviewItem | None:
        item = self._close(item_id, "correct", "corrected", who, new_value, reason)
        if item is not None and self.on_correct is not None:
            self.on_correct(item, new_value)
        return item

    def add(self, item: ReviewItem) -> ReviewItem:
        self.items[item.item_id] = item
        self._save()
        return item

    def _close(
        self,
        item_id: str,
        action: str,
        status: str,
        who: str,
        new_value: Any | None,
        reason: str | None,
    ) -> ReviewItem | None:
        item = self.items.get(item_id)
        if item is None or item.status != "pending":
            return None
        old_value = item.value
        item.status = status
        item.corrected_value = new_value
        item.reviewed_by = who
        self._save()
        if self.audit is not None:
            from engine.validation.audit import AuditEntry

            self.audit.append(
                AuditEntry(
                    entry_id=uuid.uuid4().hex[:12],
                    timestamp=_utc_now(),
                    who=who,
                    action=action,
                    field_name=item.field_name,
                    table_name=item.table_name,
                    row_index=item.row_index,
                    col_index=item.col_index,
                    old_value=old_value,
                    new_value=new_value,
                    reason=reason,
                    result_ref=item.result_ref,
                )
            )
        return item

    def _save(self) -> None:
        if self.store_path is None:
            return
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        payload = [i.to_dict() for i in self.items.values()]
        self.store_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _load(self) -> None:
        payload = json.loads(self.store_path.read_text(encoding="utf-8"))  # type: ignore[union-attr]
        self.items = {d["item_id"]: ReviewItem.from_dict(d) for d in payload}


def _utc_now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()
