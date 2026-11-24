"""Extensible content-category taxonomy with a registration mechanism.

Categories are identified by stable string ids. New categories are added at
runtime via :func:`register_category` (or a YAML/JSON profile loader later in
P1+) without rewriting the pipeline: the router consults the registry, and
every downstream module branches on category properties, not hard-coded ids.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Module = Literal["general", "industrial", "fallback"]


@dataclass(frozen=True)
class Category:
    id: str
    module: Module
    description: str = ""
    parents: tuple[str, ...] = field(default=())

    def __post_init__(self) -> None:
        if not self.id or self.id != self.id.lower().replace(" ", "_"):
            raise ValueError(f"category id must be a lowercase snake_case string: {self.id!r}")
        if self.module == "fallback" and self.id != "unknown":
            raise ValueError("only the 'unknown' category may use the fallback module")


_REGISTRY: dict[str, Category] = {}


def register_category(category: Category, *, allow_overwrite: bool = False) -> Category:
    """Register a category. Registered categories are what the router may emit."""
    existing = _REGISTRY.get(category.id)
    if existing is not None and not allow_overwrite:
        if existing != category:
            raise ValueError(f"category id already registered: {category.id}")
    _REGISTRY[category.id] = category
    return category


def get_category(category_id: str) -> Category:
    """Look up a registered category by id. Raises KeyError for unknown ids."""
    return _REGISTRY[category_id]


def all_categories() -> dict[str, Category]:
    return dict(_REGISTRY)


def categories_for_module(module: Module) -> list[Category]:
    return [c for c in _REGISTRY.values() if c.module == module]


def _seed_defaults() -> None:
    defaults: list[Category] = [
        Category("document_scan", "general", "Flatbed or scanner-produced document image"),
        Category("photo_document", "general", "Photographed (not scanned) document"),
        Category("invoice", "general", "Invoice or credit note"),
        Category("receipt", "general", "Sales receipt or till slip"),
        Category("form", "general", "Filled or blank structured form"),
        Category("table_image", "general", "Image whose main content is a table"),
        Category("chart", "general", "Chart or plot image"),
        Category("screenshot_desktop", "general", "Desktop application or website screenshot"),
        Category("screenshot_mobile", "general", "Mobile application screenshot"),
        Category("diagram", "general", "Flowchart, schematic or process diagram (general)"),
        Category("pdf_multipage", "general", "Multi-page PDF document"),
        Category("industrial_hmi", "industrial", "PLC/HMI control screen or industrial dashboard"),
        Category("coil_table", "industrial", "Hot/cold coil production list or coil table"),
        Category("machine_label", "industrial", "Machine nameplate or product identifier label"),
        Category("alarm_screen", "industrial", "Alarm list or alarm detail screen"),
        Category("process_diagram", "industrial", "Industrial process diagram or P&ID"),
        Category("unknown", "fallback", "Unrecognized content; route to general with warnings"),
    ]
    for c in defaults:
        register_category(c)


_seed_defaults()
