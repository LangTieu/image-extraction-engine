"""Factory/machine profiles (P4 item 8).

A profile YAML declares matching cues, region templates, field definitions
(name, aliases, type, unit, regex, plausible range) and table schemas.
Profiles are loaded at runtime so a new factory needs no code change.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class FieldDef:
    name: str
    type: str  # "string" | "id" | "number" | "integer"
    unit: str | None = None
    aliases: tuple[str, ...] = ()
    format_regex: str | None = None
    min_value: float | None = None
    max_value: float | None = None
    seven_segment: bool = False


@dataclass(frozen=True)
class TableSchema:
    name: str
    header_aliases: dict[str, tuple[str, ...]]  # canonical column -> aliases
    id_columns: tuple[str, ...] = ()


@dataclass
class IndustrialProfile:
    name: str
    categories: tuple[str, ...]  # taxonomy ids this profile serves
    title_cues: tuple[str, ...]
    layout_anchors: tuple[str, ...]
    colors: tuple[str, ...]  # hex or named HMI palette hints
    region_templates: dict[str, tuple[float, float, float, float]]  # relative x0,y0,x1,y1
    fields: dict[str, FieldDef]
    table_schemas: dict[str, TableSchema]
    source_path: str | None = None

    def match_score(self, ocr_text: str) -> float:
        if not self.title_cues:
            return 0.0
        lowered = ocr_text.lower()
        hits = sum(1 for cue in self.title_cues if cue.lower() in lowered)
        return hits / len(self.title_cues)

    def resolve_column(self, header: str) -> str | None:
        """Map a raw table header to the canonical column name via aliases."""
        key = _norm(header)
        for canonical, aliases in self._alias_index().items():
            if key == _norm(canonical) or key in aliases:
                return canonical
        return None

    def _alias_index(self) -> dict[str, tuple[str, ...]]:
        index: dict[str, tuple[str, ...]] = {}
        for schema in self.table_schemas.values():
            for canonical, aliases in schema.header_aliases.items():
                index[canonical] = tuple(_norm(a) for a in aliases)
        for f in self.fields.values():
            index.setdefault(f.name, tuple(_norm(a) for a in f.aliases))
        return index


def _norm(text: str) -> str:
    return " ".join(text.strip().lower().split())


def _as_str_tuple(value: Any) -> tuple[str, ...]:
    """Coerce a YAML scalar or list to a tuple of strings.

    YAML happily parses ``aliases: [12345]`` or ``title_cues: [ LÔ 12 ]``
    into ints/floats; downstream code expects strings.
    """
    if value is None:
        return ()
    if isinstance(value, (str, int, float, bool)):
        value = [value]
    return tuple(str(v).strip() for v in value if str(v).strip())


def profile_from_dict(data: dict[str, Any], source: str | None = None) -> IndustrialProfile:
    fields: dict[str, FieldDef] = {}
    for fname, spec in (data.get("fields") or {}).items():
        def _num(v: Any) -> float | None:
            try:
                return float(v) if v is not None else None
            except (TypeError, ValueError):
                return None

        fields[fname] = FieldDef(
            name=fname,
            type=spec.get("type", "string"),
            unit=spec.get("unit"),
            aliases=_as_str_tuple(spec.get("aliases")),
            format_regex=spec.get("format_regex"),
            min_value=_num(spec.get("min_value")),
            max_value=_num(spec.get("max_value")),
            seven_segment=bool(spec.get("seven_segment", False)),
        )
    schemas: dict[str, TableSchema] = {}
    for sname, spec in (data.get("table_schemas") or {}).items():
        schemas[sname] = TableSchema(
            name=sname,
            header_aliases={
                col: _as_str_tuple(aliases) for col, aliases in (spec.get("columns") or {}).items()
            },
            id_columns=_as_str_tuple(spec.get("id_columns")),
        )
    return IndustrialProfile(
        name=data.get("name", Path(source or "profile").stem),
        categories=_as_str_tuple(data.get("categories")),
        title_cues=_as_str_tuple(data.get("title_cues")),
        layout_anchors=_as_str_tuple(data.get("layout_anchors")),
        colors=_as_str_tuple(data.get("colors")),
        region_templates={
            k: tuple(v)
            for k, v in (data.get("region_templates") or {}).items()
        },
        fields=fields,
        table_schemas=schemas,
        source_path=source,
    )


def load_profile(path: str | Path) -> IndustrialProfile:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return profile_from_dict(raw, source=str(path))


def bundled_profiles() -> list[IndustrialProfile]:
    """Load every profile shipped under engine/industrial/profiles/."""
    root = resources.files("engine.industrial").joinpath("profiles")
    profiles: list[IndustrialProfile] = []
    if not root.is_dir():
        return profiles
    for item in sorted(root.iterdir(), key=lambda p: p.name):
        if item.name.endswith((".yaml", ".yml")):
            profiles.append(load_profile(str(item)))
    return profiles


def match_profile(
    ocr_text: str,
    *,
    category: str | None = None,
    profiles: list[IndustrialProfile] | None = None,
) -> IndustrialProfile | None:
    """Best profile by title-cue overlap, optionally restricted to a category."""
    pool = profiles if profiles is not None else bundled_profiles()
    if category is not None:
        pool = [p for p in pool if not p.categories or category in p.categories]
    best, best_score = None, 0.0
    for profile in sorted(pool, key=lambda p: p.name):
        score = profile.match_score(ocr_text)
        # Strict >, with the pool name-sorted first: equal scores resolve
        # deterministically instead of by list order.
        if score > best_score:
            best, best_score = profile, score
    return best if best is not None and best_score > 0.0 else None
