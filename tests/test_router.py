"""P2 tests: Smart Router feature scoring, keyword cues, fallback, rules."""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from engine.router.router import (
    DOCUMENT_KEYWORDS,
    HMI_KEYWORDS,
    RouteFeatures,
    SmartRouter,
    extract_features,
    extract_keywords,
    route_image,
)
from engine.schema.taxonomy import get_category


def _font(size: int = 28):
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size)
    except OSError:
        return ImageFont.load_default()


def _document_image() -> np.ndarray:
    """Black text on white: high text density, low colour."""
    img = Image.new("RGB", (400, 300), "white")
    draw = ImageDraw.Draw(img)
    font = _font()
    for i in range(8):
        draw.text((20, 20 + i * 34), "invoice total customer date", fill="black", font=font)
    return np.asarray(img)


def test_extract_keywords_hmi_and_document():
    hmi = extract_keywords("PLC ALARM setpoint RPM")
    assert "plc" in hmi and "alarm" in hmi and "setpoint" in hmi
    assert all(k in HMI_KEYWORDS for k in hmi)
    doc = extract_keywords("Hóa đơn - Tổng tiền, khách hàng")
    assert "hóa đơn" in doc and "tổng" in doc and "khách" in doc
    assert all(k in DOCUMENT_KEYWORDS for k in doc)
    assert extract_keywords("") == []


def test_extract_features_ranges():
    feats = extract_features(_document_image())
    assert feats.aspect_ratio == pytest.approx(400 / 300)
    assert feats.edge_density > 0.0  # gradient sum: text edges give a strong response
    assert 0.0 <= feats.colorfulness <= 1.0
    assert 0.0 <= feats.hmi_color_ratio <= 1.0
    assert 0.0 <= feats.flat_area_ratio <= 1.0
    assert 0.0 <= feats.text_pixel_density <= 1.0


def test_route_document_text_beats_hmi():
    feats = RouteFeatures(
        aspect_ratio=1.0,
        edge_density=0.1,
        colorfulness=0.0,
        hmi_color_ratio=0.0,
        flat_area_ratio=0.9,
        text_pixel_density=0.5,
    )
    decision = route_image(None, ocr_text="", features=feats)
    assert decision.category.id == "photo_document"
    assert decision.confidence >= 0.3
    assert decision.route_warning is None


def test_route_unknown_when_best_below_threshold():
    feats = RouteFeatures(
        aspect_ratio=1.0,
        edge_density=0.01,
        colorfulness=1.0,  # colourful: hurts photo_document
        hmi_color_ratio=0.0,
        flat_area_ratio=0.0,
        text_pixel_density=0.0,
    )
    decision = route_image(None, ocr_text="", features=feats)
    assert decision.category.id == "unknown"
    assert decision.route_warning is not None and "below 0.3" in decision.route_warning
    assert decision.confidence < 0.3


def test_keyword_cues_boost_scores():
    feats = RouteFeatures(
        aspect_ratio=1.0,
        edge_density=0.0,
        colorfulness=0.0,
        hmi_color_ratio=0.0,
        flat_area_ratio=0.0,
        text_pixel_density=0.0,
    )
    base = route_image(None, ocr_text="", features=feats).scores
    with_hmi = route_image(None, ocr_text="PLC ALARM setpoint", features=feats).scores
    with_doc = route_image(None, ocr_text="invoice tổng", features=feats).scores
    assert with_hmi["industrial_hmi"] == pytest.approx(base["industrial_hmi"] + 0.4)
    assert with_doc["photo_document"] == pytest.approx(base["photo_document"] + 0.4)
    decision = route_image(None, ocr_text="temperature rpm fault", features=feats)
    assert decision.keywords == sorted({"temperature", "rpm", "fault"})


def test_router_feature_extraction_matches_route_image():
    img = _document_image()
    direct = route_image(img, ocr_text="invoice total")
    via_router = SmartRouter().route(img, ocr_text="invoice total")
    assert direct.category.id == via_router.category.id
    assert direct.scores == via_router.scores


def test_register_rule_override():
    router = SmartRouter()
    target = get_category("industrial_hmi")

    def rule(features, ocr_text):
        if ocr_text == "force-hmi":
            from engine.router.router import RouteDecision

            return RouteDecision(category=target, confidence=1.0)
        return None  # fall through

    router.register_rule(rule)
    img = np.zeros((10, 10, 3), dtype=np.uint8)
    hit = router.route(img, ocr_text="force-hmi")
    assert hit.category.id == "industrial_hmi" and hit.confidence == 1.0
    fallback = router.route(img, ocr_text="")
    assert fallback.category.id != "industrial_hmi" or fallback.scores  # fell through to scoring
    assert fallback.category is not None
