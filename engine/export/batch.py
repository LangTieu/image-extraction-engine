"""Batch export: run several exporters over many results, then a manifest.

``export_batch`` never raises for a single failing exporter: the failure is
recorded under ``errors`` so one bad format cannot lose the other outputs.
The manifest records every artifact with its MIME type and sha256 checksum
(plus all exported columns), making every artifact traceable to its source
file and validator run. ``options.zip_bundle`` additionally packs artifacts
+ manifest into ``bundle.zip``.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

from engine.export.base import EXPORTERS, ExportOptions, get_exporter
from engine.schema.models import ExtractionResult

MANIFEST_NAME = "manifest.json"


def export_batch(
    results: list[ExtractionResult],
    out_dir: Path | str,
    formats: list[str] | None = None,
    options: ExportOptions | None = None,
) -> dict[str, Any]:
    """Export every result to ``out_dir`` in the requested formats.

    ``formats`` defaults to each result's own ``exports`` list, always plus
    ``json``. The output for result *i* is ``<stem>.<format>`` where
    ``<stem>`` is the source file name without extension.
    """
    options = options or ExportOptions()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {"files": [], "errors": []}
    for result in results:
        stem = (result.source.file_name if result.source else "result").rsplit(".", 1)[0]
        if formats:
            wanted = list(dict.fromkeys([*formats, "json"]))
        else:
            wanted = sorted({*result.exports, "json"})
        for fmt in wanted:
            if fmt not in EXPORTERS:
                manifest["errors"].append(f"{stem}.{fmt}: unknown exporter {fmt!r}")
                continue
            try:
                art = get_exporter(fmt).export(result, out / f"{stem}.{fmt}", options)
                manifest["files"].append({
                    "result": stem,
                    "format": fmt,
                    "path": art.path.name,
                    "mime": art.mime,
                    "sha256": art.checksum,
                })
            except Exception as exc:  # one bad artifact must not lose the rest
                manifest["errors"].append(f"{stem}.{fmt}: {exc}")
    if options.zip_bundle and manifest["files"]:
        zpath = out / "bundle.zip"
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in manifest["files"]:
                zf.write(out / f["path"], f["path"])
            zf.writestr(MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=2))
        manifest["bundle"] = zpath.name
    return manifest


def write_manifest(manifest: dict[str, Any], out_dir: Path | str) -> Path:
    path = Path(out_dir) / MANIFEST_NAME
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
