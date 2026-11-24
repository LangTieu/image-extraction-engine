# Input Specification (P0)

## Supported formats and limits

| Item | Default limit | Notes |
|---|---|---|
| File formats | JPG/JPEG, PNG, WEBP, PDF | Screenshots arrive as PNG/JPG. TIFF is a candidate to add later. |
| Max file size | 50 MB per file | Configurable per deployment. |
| Max resolution | 8000 x 8000 px | Larger images are downscaled with a RESOLUTION_CAPPED warning; originals are never modified. |
| Max PDF pages | 100 pages per PDF | Pages beyond the limit produce a typed error, not a silent truncation. |
| Max batch size | 50 files per job | Larger uploads must be split into multiple jobs (P7). |

## Color modes

- Grayscale, RGB and RGBA are accepted. Alpha is flattened onto white.
- CMYK JPEGs are converted to RGB.
- Palette PNGs are expanded to RGB.
- Binarized ("bitonal") scans are accepted as-is; preprocessing may re-normalize.

## Corrupt and unsupported files

Corrupt, truncated or unsupported files are rejected with **typed errors**
(`UnsupportedFormatError`, `CorruptFileError`, `FileTooLargeError`,
`TooManyPagesError`) - never a crash. A batch continues past a rejected
file, and the per-file result carries the error and `extraction_status:
"failed"`.

## Content categories

The router outputs one of the registered category ids. The taxonomy lives in
`engine/schema/taxonomy.py` and is **extensible without rewriting the
pipeline**: new categories are added via `register_category(Category(...))`
(or a future YAML/JSON profile loader); the router and downstream modules
branch on `Category.module` and category properties, never on hard-coded id
lists.

General (`module: general`):
`document_scan`, `photo_document`, `invoice`, `receipt`, `form`,
`table_image`, `chart`, `screenshot_desktop`, `screenshot_mobile`,
`diagram`, `pdf_multipage`

Industrial (`module: industrial`):
`industrial_hmi`, `coil_table`, `machine_label`, `alarm_screen`,
`process_diagram`

Fallback (`module: fallback`): `unknown` - routed to the general pipeline
with a warning attached.

### Extension mechanism (summary)

1. Define `Category(id="...", module="...", description="...")`.
2. Call `register_category(cat)`. Duplicate ids with different definitions raise.
3. The router emits the new id once its classifier supports it; until then it
   emits `unknown`. No pipeline code changes are required for the schema,
   validation or export layers, which are category-agnostic.

## Language requirements

- Vietnamese text **with full diacritics** (e.g. "Hoa don gia tri gia tang"
  written with diacritics in real data) and English text must be recognized
  and preserved exactly.
- Digits and alphanumeric product identifiers (coil IDs, product codes) are
  treated as their own recognition class because confusable glyphs
  (0/O, 1/I/l, 8/B) matter in IDs.
- Text blocks carry a `language` field (BCP-47: `vi`, `en`); mixed-language
  documents may mix languages per block.

## Privacy and security constraints

See [privacy.md](privacy.md). Summary: **the default deployment is
local-only**; any external vision API is strictly opt-in and configurable.

## Industrial field dictionary

Coil fields (ZONE, HOT_COIL_NO, COLD_COIL_NO, THICK, WIDTH, WEIGHT, LENGTH,
PRODUCT_CODE) with types, units, format regexes and plausible ranges are
defined in `engine/schema/industrial_fields.py`. Factory-specific formats
and ranges are marked configurable and are overridden by per-factory
profiles in P4; the dictionary here holds the engine defaults.
