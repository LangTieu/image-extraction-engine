"""Persistence layer (P7): SQLAlchemy 2.x models + a small repository API.

SQLite by default (``sqlite:///./data/service.db``); a PostgreSQL URL works
unchanged. JSON columns use a portable JSON serializer so the same models run
on both backends.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import JSON, DateTime, Float, Integer, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from service.core.settings import settings


class Base(DeclarativeBase):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class JobModel(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    profile: Mapped[str | None] = mapped_column(String(50), default=None)
    options: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(String(2000), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class JobFileModel(Base):
    __tablename__ = "job_files"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    job_id: Mapped[str] = mapped_column(String(40), index=True)
    file_name: Mapped[str] = mapped_column(String(500))
    stored_path: Mapped[str] = mapped_column(String(1000))
    mime_type: Mapped[str | None] = mapped_column(String(100), default=None)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    # queued | processing | needs_review | completed | failed
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    # {"xlsx": {"path":..., "mime":..., "checksum":...}, ...}
    exports: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    confidence: Mapped[float | None] = mapped_column(Float, default=None)
    error: Mapped[str | None] = mapped_column(String(2000), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


_engine = None
_session_factory: sessionmaker[Session] | None = None


def get_engine():
    global _engine
    if _engine is None:
        if settings.db_url.startswith("sqlite:///"):
            Path(settings.db_url.removeprefix("sqlite:///")).parent.mkdir(
                parents=True, exist_ok=True
            )
        _engine = create_engine(
            settings.db_url,
            connect_args=(
                {"check_same_thread": False} if settings.db_url.startswith("sqlite") else {}
            ),
        )
        Base.metadata.create_all(_engine)
    return _engine


def get_session() -> Session:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
    return _session_factory()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Guarantee the Session's connection is returned to the pool.

    Every caller must use this (or the FastAPI ``get_db`` dependency) instead of
    a bare ``get_session()``: a session that is never closed keeps its
    connection checked out and exhausts the QueuePool under load.
    """
    session = get_session()
    try:
        yield session
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency form of :func:`session_scope`."""
    session = get_session()
    try:
        yield session
    finally:
        session.close()


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)
