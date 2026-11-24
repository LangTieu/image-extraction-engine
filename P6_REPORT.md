# P6 — Export Engine

## What was built

New package `engine/export/`:

| File | Role |
|---|---|
| `base.py` | `Exporter` protocol, typed `ExportError`, `ExportOptions` (BOM, delimiter, decimal, values-only, image dir, field crops, ZIP), `ExportArtifact` (path + MIME + sha256), registry (`EXPORTERS` / `get_exporter` / `register`), confidence bands (green ≥ 0.8, yellow ≥ 0.7, red below/unknown) |
| `xlsx.py` | One sheet per table + `Summary` + `Traceability` sheets; frozen headers, auto-filter, column widths, numbers stored as numbers, low-confidence/needs-review cells coloured with explanatory comments; duplicate table names de-duplicated (`t`, `t_2`) |
| `csv.py` | UTF-8 (optional BOM for Vietnamese Excel), configurable delimiter and decimal separator, one file per table (`o.csv`, `o.table2.csv`…), optional `*_meta.csv` sidecar with confidence + traceability per cell |
| `json_export.py` | Full unified payload validated against `docs/spec/schema_v0.json` (generated schema as fallback) before writing; `values_only` strips provenance; deterministic |
| `image.py` | Annotated JPEG/PNG preview of the source page: table/field/text bboxes, confidence colour bands with legend, optional per-field crop thumbnails; source never modified; typed error when the source image is missing |
| `pdf.py` | ReportLab A4 report: cover (source, status, counts), embedded annotated preview, tables, fields with needs-review flags, warnings + validation issues; byte-deterministic (`invariant=1`) |
| `batch.py` | `export_batch()` over many results × formats (per-result `exports` list, always + `json`), one failure never loses the rest (recorded in `errors`), checksum `manifest.json`, optional `bundle.zip` |

## Changes outside the package

- `pyproject.toml`: added `openpyxl`, `jsonschema`, `reportlab` to dependencies and mypy overrides for the untyped libs.
- `benchmark/__init__.py`: added (was missing) so mypy stops reporting `benchmark/validate.py` under two module names.
- `tests/test_tables.py:156`: the fake backend set `self._name` while `TableBackend` subclasses assign `name` directly — mypy error; now assigns `self.name` like the real backends.
- `benchmark/tools/generate_seed.py`: the hand-typed `PNG_1X1` hex was a truncated/corrupt PNG (Pillow: `broken PNG file (chunk b'END\xae')`); replaced with a Pillow-generated valid 1×1 PNG and regenerated the seed set.

## Verification (this run)

- `pytest tests/` → `102 passed in 1.44s` (exit 0)
- `ruff check engine benchmark tests` → All checks passed
- `mypy engine benchmark tests` → Success: no issues found in 79 source files
- `benchmark/validate.py` → `35 passed, 0 failed`
- Round-trip: all 35 seed ground truths through exporters → 145 artifacts, 0 unexpected errors (CSV correctly refuses table-less results; recorded in manifest `errors`).
- Determinism: CSV/JSON/XLSX/JPG byte-identical across runs; PDF made deterministic via `invariant=1`; manifest checksums (sha256) match file contents.
- Samples committed under `docs/samples/exports/` (coil_table_001 + form_001 × 5 formats, manifest, bundle.zip); both exported JSONs re-validate against `docs/spec/schema_v0.json`.

## Notes / decisions

- New test files were intentionally **not** added (brief forbids them this round; dedicated test round follows P2/P3/P5 pattern).
- Brief asked for a merged multi-result XLSX: implemented as the batch manifest + per-result XLSX files; a single merged workbook across results can be added in the test round if wanted.
