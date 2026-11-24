"""Unit tests for the unified output schema and JSON Schema export."""

import json

import pytest

from engine.schema import (
    BBox,
    ExtractionResult,
    FieldValue,
    SourceInfo,
    TextBlock,
    all_categories,
    export_json_schema,
    get_category,
)


def plan_example_result() -> dict:
    """The unified-output example from the plan, unchanged."""
    return {
        "document_type": "industrial_hmi",
        "extraction_status": "completed",
        "tables": [
            {
                "table_name": "coil_list",
                "columns": [
                    "ZONE",
                    "HOT_COIL_NO",
                    "COLD_COIL_NO",
                    "THICK",
                    "WIDTH",
                    "WEIGHT",
                    "LENGTH",
                    "PRODUCT_CODE",
                ],
                "rows": [],
                "confidence": 0.98,
            }
        ],
        "warnings": [],
        "exports": ["xlsx", "csv", "json", "jpg"],
    }


class TestPlanExampleValidates:
    def test_plan_example_against_unified_schema(self):
        result = ExtractionResult.model_validate(plan_example_result())
        assert result.document_type == "industrial_hmi"
        assert result.extraction_status == "completed"
        assert result.tables[0].table_name == "coil_list"
        assert len(result.tables[0].columns) == 8
        assert result.tables[0].rows == []
        assert result.exports == ["xlsx", "csv", "json", "jpg"]

    def test_plan_example_has_no_warnings_and_industrial_category_registered(self):
        result = ExtractionResult.model_validate(plan_example_result())
        assert result.warnings == []
        assert get_category(result.document_type).module == "industrial"


class TestModelRoundTrip:
    def test_full_result_round_trips_through_json(self):
        result = ExtractionResult(
            document_type="form",
            extraction_status="completed_with_warnings",
            source=SourceInfo(file_name="a.png"),
            text_blocks=[
                TextBlock(
                    text="Hoa don gia tri gia tang",
                    language="vi",
                    confidence=0.9,
                    bbox=BBox(x0=1, y0=2, x1=3, y1=4),
                )
            ],
            fields=[
                FieldValue(
                    name="invoice_number",
                    value="2026/000123",
                    type="id",
                    confidence=0.9,
                )
            ],
            warnings=["RESOLUTION_CAPPED"],
        )
        data = json.loads(result.model_dump_json(exclude_none=True))
        again = ExtractionResult.model_validate(data)
        assert again == result

    def test_confidence_bounds_enforced(self):
        with pytest.raises(Exception):
            FieldValue(name="x", value="y", confidence=1.5)

    def test_invalid_status_rejected(self):
        bad = {**plan_example_result(), "extraction_status": "done"}
        with pytest.raises(Exception):
            ExtractionResult.model_validate(bad)


class TestJsonSchemaExport:
    def test_export_json_schema_is_draft_2020_12(self):
        schema = export_json_schema()
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert schema["title"] == "ExtractionResult"
        assert "tables" in schema["properties"]


class TestTaxonomyExtensibility:
    def test_defaults_registered(self):
        cats = all_categories()
        assert "industrial_hmi" in cats
        assert get_category("unknown").module == "fallback"

    def test_register_new_category_without_pipeline_changes(self):
        from engine.schema import Category, register_category

        cat = Category(id="safety_sign", module="industrial", description="Safety signage photo")
        register_category(cat)
        assert get_category("safety_sign") is cat

    def test_duplicate_registration_with_different_definition_raises(self):
        from engine.schema import Category, register_category

        with pytest.raises(ValueError):
            register_category(Category(id="form", module="industrial"))

    def test_fallback_module_reserved_for_unknown(self):
        from engine.schema import Category, register_category

        with pytest.raises(ValueError):
            register_category(Category(id="other", module="fallback"))
