# P6 fix round — bugs found by the P6 review

Branch `p6-review`. Probe: `verify_p6_review.py` (writes only under `/tmp/probe_p6/`).
Verification this run: `.venv/bin/python -m pytest -q` → 102 passed; every probe line green
(A1 determinism, A2 unique names, A4 numeric whitelist, A5 cells-over-rows, A6 schema path).

## Fixed

1. **XLSX byte-determinism** (`engine/export/xlsx.py`)
   - Root cause: `openpyxl` stamps every zip entry (and `<dcterms:modified>` in
     `docProps/core.xml`) with the current time on `save()`.
   - Fix: the workbook is saved to a buffer, then rewritten entry-by-entry with fixed
     `ZipInfo` timestamps (1980-01-01) and a pinned `modified` value. Verified: two exports
     1.2 s apart now have identical sha256.

2. **Duplicate result stems no longer overwrite silently** (`engine/export/batch.py`)
   - Chosen approach: **(a) unique file names**. The first result keeps `dup.csv`; later ones
     get the first free `dup_2.csv`, `dup_3.csv`, … suffix. The manifest entry points at the
     file actually written (probe A2 shows `dup.csv` + `dup_2.csv` with distinct checksums).
   - Documented in the `export_batch` docstring. `write_manifest` also raises `ValueError`
     instead of overwriting an existing manifest.

3. **Manifest tracks every written file** (`engine/export/base.py`, `csv.py`, `batch.py`)
   - `ExportArtifact` gained `extra_artifacts: list[ExportArtifact]` (default empty).
   - The CSV exporter returns its `tableN.csv` and `_meta.csv` sidecars there; the batch
     manifest records one entry (path, MIME, sha256) per artifact, primary and secondary.

4. **`_as_number` no longer accepts garbage** (`engine/export/xlsx.py`)
   - Only strict numeric literals become numbers: optional sign, digits, one optional decimal
     separator (`.` or the configured one). `NaN`, `Inf`, `1e3`, `12 500`, `1,234` (when `.` is
     the decimal separator) all stay text. Verified by probe A4.

5. **Cells (live readings) win over rows** (`engine/export/csv.py`, `pdf.py`, `xlsx.py`)
   - The grid starts from `rows`; every cell overwrites its `(row_index, col_index)` position;
     with no `rows` the grid is built from cells alone. The same grid builder (`csv._table_rows`)
     is now shared by the CSV, XLSX and PDF exporters. Probe A5: CSV shows `H99999`, stale
     `H00001` gone.

6. **Schema path is CWD-independent, fallback is loud** (`engine/export/json_export.py`)
   - `SCHEMA_PATH` is anchored to the repository root via `__file__`, so running from `/tmp`
     still finds `docs/spec/schema_v0.json`.
   - A schema file that exists but cannot be read/parsed raises `ExportError`;
     `contextlib.suppress(Exception)` is gone. Only a *missing* file falls back to the
     generated schema, with a `RuntimeWarning` on stderr.

7. **`values_only` JSON truly values-only** (`engine/export/json_export.py`)
   - The dead provenance-stripping loop was replaced with a working `_strip_provenance` that
     also drops top-level `extensions` (validation, review ids, …), `text_blocks`,
     `validation_results`, `processing`, `pages`.

8. **Needs-review cells without confidence are drawn** (`engine/export/image.py`)
   - A cell with `bbox` and `confidence=None` but `needs_review=True` is now drawn in red
     instead of being skipped.

9. **XLSX cell fills bounded to the data region** (`engine/export/xlsx.py`)
   - Convention (documented in `_fill_cells`): `cell.row_index=0` is the first row of the data
     grid — the first *data* row, because headers live in `columns` (seed ground truths store
     headers separately from rows). Fills outside the grid are skipped instead of mis-colouring
     the header row or footer block.

10. **`register()` refuses duplicate names** (`engine/export/base.py`)
    - Re-registering an existing exporter name now raises `ValueError` (documented) instead of
      replacing it silently — a duplicate registration is a bug, not a feature.

11. **Bundle manifest consistency** (`engine/export/batch.py`)
    - The `manifest.json` inside `bundle.zip` is now byte-identical to the on-disk manifest
      except for the bundle's own checksum, which only exists once the zip is complete
      (absent inside the zip, present on disk as `bundle.sha256`). Zip member timestamps are
      fixed, so bundles are byte-deterministic.

## Verification

- `.venv/bin/python -m pytest -q` → 102 passed (baseline before the change: 102 passed).
- `.venv/bin/python verify_p6_review.py` → all claims green (A1, A2, A4, A5, A6).

## Not done / open

- Image field-crop thumbnails are still not listed in the manifest (the review cited CSV
  sidecars; crops are optional and off by default). Trivial to add via `extra_artifacts` if
  wanted.
- An XLSX table with `cells` but no `rows` writes cell *values* via the shared grid builder;
  verified indirectly through the CSV/PDF paths.
