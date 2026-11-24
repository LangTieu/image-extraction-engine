"""Industrial routing rules (P4, add-only).

Registered on a SmartRouter with ``register_rule``; these rules only ever
*claim* images whose OCR text matches industrial vocabulary or whose
features show HMI colours. They return None otherwise, leaving the P2
behaviour untouched for every non-industrial input.
"""

from __future__ import annotations

from engine.industrial.profiles import bundled_profiles
from engine.router.router import RouteDecision, RouteFeatures, get_category

# vocabulary that claims coil-table / machine-label / alarm categories
_COIL_CUES = ("coil", "vòng", "lô", "trọng lượng", "bề rộng", "bề dày")
_LABEL_CUES = ("nameplate", "serial no", "model", "serial")
_ALARM_CUES = ("alarm", "fault", "acknowledge", "cảnh báo", "lỗi")


def industrial_rule(features: RouteFeatures, ocr_text: str) -> RouteDecision | None:
    """Claim industrial images by keyword vocabulary; None = not claimed."""
    if not ocr_text:
        return None
    lowered = ocr_text.lower()

    coil_hits = sum(1 for c in _COIL_CUES if c in lowered)
    if coil_hits >= 2:
        return RouteDecision(
            category=get_category("coil_table"),
            confidence=min(1.0, 0.5 + 0.2 * coil_hits),
            scores={"coil_table": min(1.0, 0.5 + 0.2 * coil_hits)},
            reasons=[f"P4 industrial rule: coil vocabulary hits={coil_hits}"],
        )
    if features.hmi_color_ratio > 0.25 and any(c in lowered for c in _ALARM_CUES):
        return RouteDecision(
            category=get_category("alarm_screen"),
            confidence=0.7,
            scores={"alarm_screen": 0.7},
            reasons=["P4 industrial rule: HMI colours + alarm vocabulary"],
        )
    if any(c in lowered for c in _LABEL_CUES):
        return RouteDecision(
            category=get_category("machine_label"),
            confidence=0.6,
            scores={"machine_label": 0.6},
            reasons=["P4 industrial rule: machine-label vocabulary"],
        )
    profile_pool = bundled_profiles()
    if profile_pool and any(p.match_score(ocr_text) > 0.4 for p in profile_pool):
        return RouteDecision(
            category=get_category("industrial_hmi"),
            confidence=0.55,
            scores={"industrial_hmi": 0.55},
            reasons=["P4 industrial rule: factory profile title cues"],
        )
    return None


def register_industrial_rules(router) -> None:
    """Attach P4 industrial rules to a SmartRouter (first registered, first tried)."""
    router.register_rule(industrial_rule)


__all__ = ["industrial_rule", "register_industrial_rules"]
