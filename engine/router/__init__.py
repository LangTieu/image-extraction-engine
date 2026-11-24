"""Smart Image Router (P2) — feature + keyword based category routing."""

from engine.router.router import (
    RouteDecision,
    RouteFeatures,
    SmartRouter,
    extract_features,
    extract_keywords,
    route_image,
)

__all__ = [
    "RouteDecision",
    "RouteFeatures",
    "SmartRouter",
    "extract_features",
    "extract_keywords",
    "route_image",
]
