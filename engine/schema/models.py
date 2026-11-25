"""Unified output schema for the Image Extraction Engine (P0 draft).

Pydantic v2 models matching the plan's unified data model, plus an exported
JSON Schema. Domain-specific data lives in a namespaced ``extensions``
object so the core structure never changes.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class ExtractionStatus(StrEnum):
    """Lifecycle status of one extraction result (serializes to its value)."""

    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    NEEDS_REVIEW = "needs_review"
    FAILED = "failed"


class BBox(BaseModel):
    """Axis-aligned bounding box in pixels: x0, y0, x1, y1."""

    x0: float
    y0: float
    x1: float
    y1: float

    @field_validator("x1", "y1")
    @classmethod
    def _positive_extent(cls, v: float, info: Any) -> float:
        key = "x0" if info.field_name == "x1" else "y0"
        if v <= info.data[key]:
            raise ValueError(f"{info.field_name} must be greater than {key}")
        return v


class Provenance(BaseModel):
    """Source position of one node: page + bbox in original-image coordinates.

    ``page`` is 0-based (matching ``SourceInfo.page`` and
    ``engine/ocr/pdf.py:PageText.page_index``). ``scale`` records the render
    factor (DPI / 72) used for PDF pages so multi-scale pages stay traceable.
    """

    page: int | None = None
    bbox: BBox
    coord_space: Literal["original"] = "original"
    unit: Literal["px"] = "px"
    scale: float | None = None


class SourceInfo(BaseModel):
    file_name: str
    page: int | None = None
    sha256: str | None = None


class Page(BaseModel):
    page_number: int
    width_px: int | None = None
    height_px: int | None = None
    dpi: float | None = None


class TextBlock(BaseModel):
    text: str
    bbox: BBox | None = None
    reading_order: int | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    language: str | None = None  # BCP-47, e.g. "vi", "en"
    prov: list[Provenance] = []


class ValidationIssue(BaseModel):
    id: str
    severity: Literal["error", "warning", "info"]
    message: str


class Cell(BaseModel):
    row_index: int
    col_index: int
    row_span: int = 1
    col_span: int = 1
    bbox: BBox | None = None
    text: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    needs_review: bool = False
    validation_results: list[ValidationIssue] = []
    warnings: list[str] = []
    proposals: list[str] = []  # ambiguity candidates when needs_review
    prov: list[Provenance] = []


class Table(BaseModel):
    table_name: str | None = None
    columns: list[str] = []
    rows: list[list[str | None]] = []
    cells: list[Cell] = []
    bbox: BBox | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    needs_review: bool = False
    validation_results: list[ValidationIssue] = []
    prov: list[Provenance] = []


class FieldValue(BaseModel):
    name: str
    value: str | int | float | bool | None = None
    raw_text: str | None = None
    unit: str | None = None
    type: str | None = None  # e.g. "string", "number", "id"
    confidence: float | None = Field(default=None, ge=0, le=1)
    bbox: BBox | None = None
    cell_ref: Cell | None = None
    prov: list[Provenance] = []
    needs_review: bool = False
    validation_results: list[ValidationIssue] = []
    proposals: list[str] = []  # ambiguity candidates when needs_review


class ProcessingMeta(BaseModel):
    pipeline_path: list[str] = []  # e.g. ["router", "preprocessing", "general"]
    module_versions: dict[str, str] = {}
    timings_ms: dict[str, float] = {}


class ExtractionResult(BaseModel):
    """Top-level result for one input file (or one page group of a PDF)."""

    document_type: str  # a registered category id, e.g. "industrial_hmi"
    extraction_status: ExtractionStatus
    job_id: str | None = None
    source: SourceInfo | None = None
    pages: list[Page] = []
    text_blocks: list[TextBlock] = []
    tables: list[Table] = []
    fields: list[FieldValue] = []
    validation_results: list[ValidationIssue] = []
    warnings: list[str] = []
    exports: list[str] = []  # e.g. ["xlsx", "csv", "json", "jpg"]
    processing: ProcessingMeta | None = None
    # Namespaced domain extensions, e.g. {"industrial": {...}}. Core never changes.
    extensions: dict[str, dict[str, Any]] = {}


def export_json_schema(result_type: type[ExtractionResult] = ExtractionResult) -> dict[str, Any]:
    """Export the unified schema as JSON Schema (draft 2020-12)."""
    schema = result_type.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    return schema
