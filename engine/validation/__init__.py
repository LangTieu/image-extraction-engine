"""Validation & confidence layer (P5).

Re-exports the public API so callers can ``from engine.validation import ...``.
"""

from engine.schema.models import ExtractionResult, ExtractionStatus, FieldValue, ValidationIssue
from engine.validation.ambiguity import AmbiguityOutcome, resolve_ambiguity
from engine.validation.anomalies import detect_anomalies
from engine.validation.confidence import (
    IsotonicCalibrator,
    PlattCalibrator,
    doc_confidence,
    ece,
    field_confidence,
    reliability_diagram,
)
from engine.validation.normalize import normalize_date, normalize_number
from engine.validation.review import ReviewBackend, ReviewItem, ReviewThresholds
from engine.validation.rules import Finding, Rule, load_rules
from engine.validation.validate_result import validate_result

__all__ = [
    "AmbiguityOutcome",
    "ExtractionResult",
    "ExtractionStatus",
    "FieldValue",
    "Finding",
    "IsotonicCalibrator",
    "PlattCalibrator",
    "ReviewBackend",
    "ReviewItem",
    "ReviewThresholds",
    "Rule",
    "ValidationIssue",
    "detect_anomalies",
    "doc_confidence",
    "ece",
    "field_confidence",
    "load_rules",
    "normalize_date",
    "normalize_number",
    "reliability_diagram",
    "resolve_ambiguity",
    "validate_result",
]
