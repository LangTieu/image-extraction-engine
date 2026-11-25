"""Unified output schema: models, taxonomy registry and industrial dictionary."""

from engine.schema.industrial_fields import (
    DEFAULT_FIELDS,
    IndustrialField,
    get_field,
    validate_value,
)
from engine.schema.models import (
    BBox,
    Cell,
    ExtractionResult,
    ExtractionStatus,
    FieldValue,
    Page,
    ProcessingMeta,
    Provenance,
    SourceInfo,
    Table,
    TextBlock,
    ValidationIssue,
    export_json_schema,
)
from engine.schema.taxonomy import (
    Category,
    all_categories,
    categories_for_module,
    get_category,
    register_category,
)

__all__ = [
    "DEFAULT_FIELDS",
    "BBox",
    "Category",
    "Cell",
    "ExtractionResult",
    "ExtractionStatus",
    "FieldValue",
    "IndustrialField",
    "Page",
    "ProcessingMeta",
    "Provenance",
    "SourceInfo",
    "Table",
    "TextBlock",
    "ValidationIssue",
    "all_categories",
    "categories_for_module",
    "export_json_schema",
    "get_category",
    "get_field",
    "register_category",
    "validate_value",
]
