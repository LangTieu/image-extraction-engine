"""Pydantic wire models for the API (openapi.json contract)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

JobStatus = Literal["queued", "processing", "needs_review", "completed", "failed"]


class JobFileOut(BaseModel):
    id: str
    file_name: str
    status: JobStatus
    mime_type: str | None = None
    size_bytes: int = 0
    confidence: float | None = None
    error: str | None = None
    result: dict[str, Any] | None = None
    exports: dict[str, Any] = Field(default_factory=dict)


class JobOut(BaseModel):
    id: str
    status: JobStatus
    profile: str | None = None
    options: dict[str, Any] = Field(default_factory=dict)
    progress: int = 0
    error: str | None = None
    created_at: datetime
    updated_at: datetime
    files: list[JobFileOut] = Field(default_factory=list)


class JobCreated(BaseModel):
    job_id: str
    status: JobStatus = "queued"
    files: int
