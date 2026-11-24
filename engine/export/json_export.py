"""JSON exporter: full unified-schema payload, validated against
``docs/spec/schema_v0.json`` (falling back to the generated schema) before
writing. ``options.values_only`` strips provenance (bbox, cells, validation)
and keeps values. Deterministic: no timestamps, sorted dict keys off.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from jsonschema import Draft202012Validator

from engine.export.base import ExportArtifact, ExportError, ExportOptions, artifact
from engine.schema.models import ExtractionResult, export_json_schema

SCHEMA_PATH = Path("docs/spec/schema_v0.json")


@lru_cache(maxsize=1)
def _schema() -> dict:
    if SCHEMA_PATH.is_file():
        import contextlib

        with contextlib.suppress(Exception):
            return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return export_json_schema()


def _strip_provenance(payload: dict) -> dict:
    payload = json.loads(json.dumps(payload))  # deep copy
    for t in payload.get("tables", []):
        t.pop("cells", None)
        t.pop("bbox", None)
        t.pop("validation_results", None)
        for r in t.get("rows", []):
            pass
    for f in payload.get("fields", []):
        f.pop("bbox", None)
        f.pop("cell_ref", None)
        f.pop("validation_results", None)
        f.pop("raw_text", None)
        f.pop("proposals", None)
    payload.pop("text_blocks", None)
    payload.pop("validation_results", None)
    payload.pop("processing", None)
    payload.pop("pages", None)
    return payload


class JsonExporter:
    name = "json"

    def export(
        self, result: ExtractionResult, out_path: Path | str, options: ExportOptions | None = None
    ) -> ExportArtifact:
        options = options or ExportOptions()
        out = Path(out_path)
        if out.suffix.lower() != ".json":
            raise ExportError(self.name, f"expected a .json path, got {out.name!r}")
        payload = result.model_dump(mode="json")
        if options.values_only:
            payload = _strip_provenance(payload)
        validator = Draft202012Validator(_schema())
        errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.path))
        if errors:
            first = errors[0]
            msg = f"result failed schema validation at {list(first.path)}: {first.message}"
            raise ExportError(self.name, msg)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return artifact(out, "application/json")


def make():
    return JsonExporter()
