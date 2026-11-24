"""Tests for the industrial field dictionary."""

import pytest

from engine.schema import DEFAULT_FIELDS, get_field, validate_value

REQUIRED_FIELDS = [
    "ZONE",
    "HOT_COIL_NO",
    "COLD_COIL_NO",
    "THICK",
    "WIDTH",
    "WEIGHT",
    "LENGTH",
    "PRODUCT_CODE",
]


class TestDictionaryCompleteness:
    def test_all_required_fields_defined(self):
        assert set(REQUIRED_FIELDS) <= set(DEFAULT_FIELDS)

    def test_coil_fields_have_type_and_documentation(self):
        for name in REQUIRED_FIELDS:
            spec = get_field(name)
            assert spec.type in {"string", "id", "number", "integer"}, name
            assert spec.description, name

    def test_numeric_fields_have_units(self):
        for name, unit in [("THICK", "mm"), ("WIDTH", "mm"), ("WEIGHT", "kg"), ("LENGTH", "m")]:
            assert get_field(name).unit == unit

    def test_unknown_field_lookup_raises(self):
        with pytest.raises(KeyError):
            get_field("NOT_A_FIELD")


class TestValueValidation:
    def test_valid_coil_id(self):
        assert validate_value("HOT_COIL_NO", "H26-0142") == []

    def test_reject_empty_coil_id(self):
        assert validate_value("HOT_COIL_NO", "") != []

    def test_thickness_within_range(self):
        assert validate_value("THICK", "1.20") == []

    def test_thickness_above_plausible_range_flagged(self):
        problems = validate_value("THICK", "700.0")
        assert any("maximum" in p for p in problems)

    def test_weight_non_numeric_flagged(self):
        assert validate_value("WEIGHT", "heavy") != []

    def test_product_code_with_grade(self):
        assert validate_value("PRODUCT_CODE", "SPHC-1.2x1250") == []
