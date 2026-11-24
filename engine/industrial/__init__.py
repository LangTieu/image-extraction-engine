"""Industrial Vision module (P4).

Screens and factory-floor photos: profile-driven parsing of HMI screens,
coil tables, machine labels and alarm banners. Unknown or confusable
readings are flagged, never guessed.
"""

from engine.industrial.pipeline import INDUSTRIAL_CATEGORIES, MODULE_VERSION, IndustrialVision
from engine.industrial.profiles import (
    FieldDef,
    IndustrialProfile,
    TableSchema,
    load_profile,
    match_profile,
    profile_from_dict,
)
from engine.industrial.regions import DetectorModelHook, Region, RegionType
from engine.industrial.screen import ScreenReport, normalize_screen
from engine.industrial.vision_assist import VisionAssistHook

__all__ = [
    "INDUSTRIAL_CATEGORIES",
    "DetectorModelHook",
    "FieldDef",
    "IndustrialProfile",
    "IndustrialVision",
    "MODULE_VERSION",
    "Region",
    "RegionType",
    "ScreenReport",
    "TableSchema",
    "VisionAssistHook",
    "load_profile",
    "match_profile",
    "normalize_screen",
    "profile_from_dict",
]
