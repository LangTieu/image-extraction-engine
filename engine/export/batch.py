"""Batch export: run several exporters over many results, then a manifest.

``export_batch`` never raises for a single failing exporter: the failure is
recorded under ``errors`` so one bad format cannot lose the other outputs.
The manifest records every artifact — primary *and* secondary files such as
CSV sidecars — with its MIME type and sha256 checksum, making every written
file traceable to its source file and validator run. ``options.zip_bundle``
additionally packs artifacts + manifest into ``bundle.zip``.

Duplicate names (P6 fix): two results with the same stem never silently
overwrite each other. The first keeps ``dup.csv``; later ones get
``dup_2.csv``, ``dup_3.csv``, ... (the first free ``<stem>_<n>`` suffix), and
the manifest entry points at the file actually written. Sidecars and bundle
members follow the same unique name. ``write_manifest`` raises ``ValueError``
on an existing manifest file, for the same reason.

Determinism (P6 fix): zip member timestamps are fixed to 1980-01-01, so the
same inputs produce byte-identical bundles.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

from engine.export.base import EXPORTERS, ExportArtifact, ExportError, ExportOptions, get_exporter
from engine.schema.models import ExtractionResult

MANIFEST_NAME = "manifest.json"
_ZIP_DATE = (1980, 1, 1, 0, 0, 0)  # fixed timestamp for deterministic bytes


def _entry(art: ExportArtifact, result: str, fmt: str) -> dict[str, Any]:
    return {
        "result": result,
        "format": fmt,
        "path": art.path.name,
        "mime": art.mime,
        "sha256": art.checksum,
    }


def export_batch(
    results: list[ExtractionResult],
    out_dir: Path | str,
    formats: list[str] | None = None,
    options: ExportOptions | None = None,
) -> dict[str, Any]:
    """Export every result to ``out_dir`` in the requested formats.

    ``formats`` defaults to each result's own ``exports`` list, always plus
    ``json``. The output for result *i* is ``<stem>.<format>`` where
    ``<stem>`` is the source file name without extension; when that name is
    already taken by an earlier artifact the stem gets the first free
    ``_<n>`` suffix (``dup.csv`` → ``dup_2.csv``) instead of overwriting it.
    """
    options = options or ExportOptions()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {"files": [], "errors": []}
    used: set[str] = set()  # every file name already written or reserved
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
                base = out / f"{stem}.{fmt}"
                n = 2
                while base.name in used:
                    base = out / f"{stem}_{n}.{fmt}"
                    n += 1
                used.add(base.name)
                art = get_exporter(fmt).export(result, base, options)
                for extra in art.extra_artifacts:
                    if extra.path.name in used:
                        raise ExportError(
                            fmt, f"secondary file name collision: {extra.path.name!r}"
                        )
                    used.add(extra.path.name)
                    manifest["files"].append(_entry(extra, stem, fmt))
                manifest["files"].append(_entry(art, stem, fmt))
            except Exception as exc:  # one bad artifact must not lose the rest
                manifest["errors"].append(f"{stem}.{fmt}: {exc}")
    if options.zip_bundle and manifest["files"]:
        zpath = out / "bundle.zip"
        in_zip = {**manifest, "bundle": {"name": zpath.name}}
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in manifest["files"]:
                data = (out / f["path"]).read_bytes()
                zf.writestr(zipfile.ZipInfo(f["path"], date_time=_ZIP_DATE), data)
            zf.writestr(
                zipfile.ZipInfo(MANIFEST_NAME, date_time=_ZIP_DATE),
                json.dumps(in_zip, ensure_ascii=False, indent=2),
            )
        # The on-disk manifest equals the in-zip one except for the bundle's
        # own checksum, which only exists once the zip is complete.
        in_zip["bundle"]["sha256"] = ExportArtifact(
            zpath, "application/zip", _sha256(zpath)
        ).checksum
        manifest["bundle"] = in_zip["bundle"]
    return manifest


def _sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_manifest(manifest: dict[str, Any], out_dir: Path | str) -> Path:
    path = Path(out_dir) / MANIFEST_NAME
    if path.exists():
        raise ValueError(f"refusing to overwrite an existing manifest: {path}")
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
