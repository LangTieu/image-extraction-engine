"""Dynamic Pydantic schemas built from profiles (P5 item 3).

A profile's field dictionary becomes a concrete Pydantic model at runtime:
required fields, types, regex formats (e.g. the coil-ID pattern) and enum
choices are enforced declaratively. Validation problems become issues with
IDs and severities, never exceptions escaping to the caller.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from dataclasses import field as dc_field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, create_model

from engine.schema.models import ValidationIssue

FieldSpec = Any  # engine.industrial.profiles.FieldDef (kept untyped to avoid an import cycle)


@dataclass(frozen=True)
class FieldContract:
    """One field's validation contract, profile-driven."""

    name: str
    type: str = "string"  # string | id | number | integer
    required: bool = False
    format_regex: str | None = None
    min_value: float | None = None
    max_value: float | None = None
    choices: tuple[str, ...] | None = None  # enum for state fields
    description: str | None = None
    aliases: tuple[str, ...] = dc_field(default=())


@dataclass
class SchemaValidationOutcome:
    valid: bool
    issues: list[ValidationIssue]
    cleaned: dict[str, Any]  # coerced values for fields that passed


def contract_from_field_def(fd: FieldSpec, *, required: bool = False) -> FieldContract:
    return FieldContract(
        name=fd.name,
        type=getattr(fd, "type", "string"),
        required=required,
        format_regex=getattr(fd, "format_regex", None),
        min_value=getattr(fd, "min_value", None),
        max_value=getattr(fd, "max_value", None),
        aliases=tuple(getattr(fd, "aliases", ()) or ()),
    )


def build_model(
    name: str,
    contracts: list[FieldContract],
) -> type[BaseModel]:
    """Build a Pydantic model class from a list of field contracts."""
    fields: dict[str, Any] = {}
    for c in contracts:
        ann: Any
        kwargs: dict[str, Any] = {"description": c.description}
        if c.type in ("number", "integer"):
            ann = float if c.type == "number" else int
            if c.min_value is not None:
                kwargs["ge"] = c.min_value
            if c.max_value is not None:
                kwargs["le"] = c.max_value
        else:
            ann = str
            if c.format_regex:
                kwargs["pattern"] = c.format_regex
            if c.choices:
                ann = Literal[c.choices]
        default = ... if c.required else None
        ann_maybe = ann | None
        fields[c.name] = (ann_maybe, Field(default=default, **kwargs))
    model = create_model(name, __config__=ConfigDict(extra="allow"), **fields)
    return model


def build_model_from_profile(
    profile: Any,
    *,
    required_fields: list[str] | None = None,
    enums: dict[str, tuple[str, ...]] | None = None,
) -> type[BaseModel]:
    """Contracts from a profile's fields dict; required/enum overrides via args."""
    required = set(required_fields or ())
    enums = enums or {}
    contracts = [
        FieldContract(
            name=fd.name,
            type=getattr(fd, "type", "string"),
            required=fd.name in required,
            format_regex=getattr(fd, "format_regex", None),
            min_value=getattr(fd, "min_value", None),
            max_value=getattr(fd, "max_value", None),
            choices=enums.get(fd.name),
            aliases=tuple(getattr(fd, "aliases", ()) or ()),
        )
        for fd in profile.fields.values()
    ]
    return build_model(f"{profile.name}_fields", contracts)


def validate_fields(
    data: dict[str, Any],
    contracts: list[FieldContract],
    model: type[BaseModel] | None = None,
) -> SchemaValidationOutcome:
    """Validate a name->raw-value mapping; problems become ValidationIssues."""
    model = model or build_model("fields", contracts)
    issues: list[ValidationIssue] = []
    cleaned: dict[str, Any] = {}
    by_name = {c.name: c for c in contracts}
    for c in contracts:
        if c.required and c.name not in data:
            issues.append(
                ValidationIssue(
                    id=f"FIELD_REQUIRED_{c.name.upper()}",
                    severity="error",
                    message=f"required field {c.name!r} is missing",
                )
            )
    for name, value in data.items():
        contract = by_name.get(name)
        if contract is None:
            cleaned[name] = value  # extra="allow": unknown fields pass through
            continue
        try:
            cleaned[name] = model.model_validate({name: value})
            cleaned[name] = getattr(cleaned[name], name)
        except Exception as exc:
            issues.append(
                ValidationIssue(
                    id=f"FIELD_FORMAT_{name.upper()}",
                    severity="error",
                    message=f"field {name!r} failed {contract.type} validation: "
                    f"{_first_line(str(exc))}",
                )
            )
    return SchemaValidationOutcome(valid=not issues, issues=issues, cleaned=cleaned)


def _first_line(text: str) -> str:
    return text.strip().splitlines()[0] if text.strip() else text


def regex_matches(pattern: str, value: str) -> bool:
    return re.fullmatch(pattern, value) is not None
