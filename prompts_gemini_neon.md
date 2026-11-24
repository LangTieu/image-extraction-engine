## Phase P0: Requirements & Data Specification
Objective
Establish the formal engineering specification, unified intermediate data schema, language and privacy rules, and initial labeled evaluation dataset for the Modular Hybrid Vision Engine prior to building processing modules.

Scope and Boundaries

- In scope: Input format and resolution rules (JPG, PNG, WEBP, PDF, screenshots), unified JSON output schema with domain extensibility, Vietnamese and English language and industrial identifier requirements, local Linux deployment and privacy constraints, and the initial benchmark dataset structure across General Vision and Industrial Vision.
- Out of scope: Implementing image preprocessing, OCR, table parsers, HMI parsers, validation rules, export generators, API endpoints, or web UI. No final model or library lock-in before benchmark evaluation.

Key Tasks and Steps

- Define supported input formats, page/image ingestion limits, and quality/resolution expectations across General Vision (documents, forms, invoices, receipts, tables, charts, reports, screenshots, multi-page PDFs) and Industrial Vision (PLC/HMI screens, hot/cold coil tables, machine parameters, alarms, process diagrams).
- Formalize the unified intermediate Pydantic/JSON output schema supporting document_type, extraction_status, tables (table_name, columns, rows, confidence), warnings, exports, source bounding-box/cell traceability metadata, and extensible domain-specific fields without breaking top-level structure.
- Specify Vietnamese + English text, numeric, unit, and compact product/coil ID conventions, plus local Linux server deployment, data retention, and privacy boundaries.
- Design the labeled benchmark dataset directory layout and annotation guidelines covering photographed documents/forms, dense multi-column small-font tables, computer/mobile screenshots, angled PLC/HMI photographs, and coil tables with compact IDs, numbers, and units.
- Document evaluation metrics and baseline thresholds (OCR CER, WER, Table Structure Accuracy, Field-level Accuracy, Coil ID exact-match rate, and per-image/batch latency) and explicitly flag where candidate selection remains provisional pending benchmarking.

Technology Candidates from the Plan

- Schema and validation modeling: Pydantic (candidate for typed schemas and domain rules).
- Target deployment baseline: Local Linux machine or server (with optional PostgreSQL and Redis evaluated later for history/queues).
- Candidate areas noted for downstream evaluation (not yet selected): OpenCV, PaddleOCR, Tesseract, Docling, Table Transformer, Qwen2.5-VL, Gemini Vision, Python + FastAPI, OpenPyXL.

Acceptance Criteria

- Unified output schema is versioned and validates sample General Vision and Industrial Vision payloads (including the industrial_hmi / coil_list structure) with explicit traceability and warning fields.
- Benchmark dataset specification covers all five real-world operating categories, including angled screens, dense tables, and Vietnamese/English mixed text.
- Privacy, local Linux constraints, and evaluation metrics (CER, WER, Table Structure Accuracy, Field-level Accuracy, Coil ID Accuracy, Processing Time) are clearly defined with no unverified accuracy claims.

Expected Deliverable
An approved Requirements & Data Specification package (docs/specs/p0-specification.md, JSON Schema / Pydantic schema definitions, and benchmarks/dataset-manifest.md + sample annotation template) ready to govern P1–P8.

## Phase P1: Image Preprocessing
Objective
Build a deterministic, modular image preprocessing pipeline that normalizes orientation, perspective distortion, noise, blur, contrast, and region crops for both General Vision and Industrial Vision inputs while preserving coordinate mappings back to source images.

Scope and Boundaries

- In scope: Ingestion of JPG, PNG, WEBP, and rendered PDF pages/screenshots; orientation correction, perspective rectification (especially angled screens/monitors), denoising, sharpening/contrast enhancement, glare/quality assessment, region/screen cropping, and coordinate transform tracking.
- Out of scope: OCR text recognition, table cell parsing, HMI semantic field extraction, confidence scoring of extracted business values, API routes, or UI screens.

Key Tasks and Steps

- Implement an image loader and quality assessor that normalizes color space/orientation and flags severe blur, low resolution, or glare in metadata/warnings rather than silently altering unreadable regions.
- Build perspective correction and screen/document boundary detection to rectify angled PLC/HMI monitors and skewed photographed documents/forms, recording transformation matrices/mappings so downstream bounding boxes can be traced.
- Implement configurable denoising, sharpening, and local contrast normalization steps tuned for small fonts, screenshots, and industrial displays without introducing synthetic artifacts or hallucinated strokes.
- Add region-of-interest (ROI) cropping utilities (such as isolating monitor/screen regions or dense table zones) while retaining source coordinates.
- Expose clean Python interfaces so individual steps can be enabled, bypassed, or tuned per input category and tested against the P0 benchmark images.

Technology Candidates from the Plan

- Image processing: OpenCV (perspective correction, denoising, cropping, contrast, region detection).
- Backend language runtime: Python (with Pydantic models for preprocessing metadata/transforms).

Acceptance Criteria

- Pipeline processes representative General Vision and Industrial Vision benchmark images without crashing and outputs normalized images plus coordinate/transform metadata.
- Angled screen photographs and skewed documents show measurable geometric rectification without clipping critical borders or inventing content.
- Low-quality inputs (blur, glare, low contrast) emit explicit quality warnings instead of failing silently.

Expected Deliverable
A Preprocessing Pipeline module (src/engine/preprocessing/) with unit and benchmark evaluation tests (tests/preprocessing/) and a short preprocessing tuning summary on the benchmark set.

## Phase P2: General OCR
Objective
Implement the General Vision OCR module to extract Vietnamese and English text, digits, and identifiers from documents, forms, screenshots, and images while preserving bounding-box coordinates and reading order.

Scope and Boundaries

- In scope: Text detection and recognition for Vietnamese diacritics, English text, numbers, and product/alphanumeric identifiers across documents, forms, charts/labels, and computer/mobile screenshots; outputting text lines/blocks with coordinates and reading order.
- Out of scope: Full multi-column table cell reconstruction (handled in P3), industrial HMI/coil semantic profile parsing (handled in P4), field-level business validation and human review UI (handled in P5/P7), and export generation (handled in P6).

Key Tasks and Steps

- Create a unified OCR result abstraction returning recognized text spans, language/script hints where available, confidence scores, bounding boxes, and reading order, mapped back to source/preprocessed coordinates.
- Integrate candidate OCR engines (PaddleOCR and Tesseract) behind a common adapter interface so they can be run and compared on identical benchmark slices.
- Handle Vietnamese and English mixed text, small UI/screenshot fonts, and compact identifiers, surfacing low-confidence spans rather than silently guessing ambiguous characters.
- Order extracted text blocks logically for single-column, multi-column, and screenshot layouts, and record any warnings when layout reading order is ambiguous.
- Run an initial comparative evaluation across General Vision benchmark images (documents/forms, screenshots, and small/blurry text cases) using CER, WER, and latency metrics.

Technology Candidates from the Plan

- OCR: PaddleOCR; Tesseract (compare language and image-quality performance).
- Image/document context: OpenCV (crop/scale helpers) and Docling (where document-level structure context is evaluated alongside OCR).

Acceptance Criteria

- Extracts Vietnamese and English text and digits with preserved bounding-box coordinates and reading order across General Vision benchmark samples.
- Both PaddleOCR and Tesseract adapters are benchmarked on the same dataset with recorded CER, WER, and processing time.
- Ambiguous or low-confidence text spans retain low confidence scores and warning flags rather than silent replacement.

Expected Deliverable
A General OCR Module (src/engine/ocr/) with engine adapters, coordinate-preserving output structures, tests, and a baseline OCR comparison note on the benchmark set.

## Phase P3: Table Extraction
Objective
Build the table detection and structure reconstruction module that identifies tables in General Vision inputs and reconstructs rows, columns, and individual cells while retaining cell-level positions and traceability.

Scope and Boundaries

- In scope: Detecting tables in photographed/scanned documents, reports, screenshots, and multi-page PDFs; reconstructing row, column, and cell grids (including dense tables with many columns and small fonts); retaining bounding boxes and cell coordinates.
- Out of scope: Industrial PLC/HMI screen-specific or coil-table domain parsing/unit normalization (handled in P4), business rule validation/confidence thresholds (handled in P5), spreadsheet/CSV/JSON export (handled in P6), and UI table editing (handled in P7).

Key Tasks and Steps

- Implement table region detection and cell/row/column structure parsing using Table Transformer and/or OpenCV + OCR coordinate alignment, alongside Docling where document/PDF structure parsing applies.
- Map OCR text spans from P2 into detected table cells using spatial overlap/alignment rules so each cell preserves its text, row/column indices, and bounding box.
- Handle dense multi-column tables, small fonts, borderless/faint-line tables, and multi-page table continuation markers, emitting structural warnings when row/column alignment is uncertain.
- Populate the tables array (table_name, columns, rows, confidence) and cell traceability metadata conformant with the P0 schema.
- Evaluate table reconstruction on dense multi-column and document/screenshot benchmark tables and log Table Structure Accuracy and latency.

Technology Candidates from the Plan

- Table recognition: Table Transformer; OpenCV + OCR (rows, columns, cell boundaries, and table reconstruction).
- Document parsing: Docling (document structure and PDF-oriented extraction).
- Vision models (optional fallback for difficult layouts, evaluated carefully): Qwen2.5-VL; Gemini Vision.

Acceptance Criteria

- Detects tables and reconstructs rows, columns, and cells with cell-level bounding-box/coordinate traceability on benchmark table images.
- Handles dense tables with many columns and small fonts, flagging uncertain cell/column assignments in warnings and confidence rather than silently corrupting columns.
- Table Structure Accuracy and processing time are measured and documented on the table benchmark subset.

Expected Deliverable
A Table Extraction Module (src/engine/tables/) integrating table detection with OCR coordinate alignment, conforming to the unified output schema, complete with tests and benchmark metrics.

## Phase P4: Industrial Vision
Objective
Implement the Industrial Vision processing module and Smart Image Router integration to classify industrial screens versus general documents/images and extract structured PLC/HMI data, hot/cold coil tables, machine parameters, alarms, and process states with units and configurable factory profiles.

Scope and Boundaries

- In scope: Content classification/routing between General Vision and Industrial Vision; PLC/HMI screen region detection; OCR and table parsing for compact industrial labels, coil IDs, numeric values (THICK, WIDTH, WEIGHT, LENGTH, etc.), units, alarms, and operating states; per-factory/per-machine configurable profiles plus a generic fallback parser.
- Out of scope: Final cross-module validation/review workflow (handled in P5), Excel/CSV/JSON/preview/PDF report generation (handled in P6), web UI and API endpoints (handled in P7), and full-system benchmark tuning (handled in P8).

Key Tasks and Steps

- Implement the Smart Image Router classifier to distinguish General Vision inputs from Industrial Vision screens (such as PLC/HMI displays and coil production tables) and route to the appropriate pipeline.
- Build screen-region and table extraction tailored to industrial layouts—including angled PLC/HMI screens and hot/cold coil tables—preserving strict column alignment and associating numeric fields with their units and column headers.
- Implement configurable factory/machine profiles (defining expected columns, identifier patterns, units, and layout zones) along with a generic fallback parser so new layouts/factories do not require rewriting the core engine.
- Support optional vision-language model reasoning (Qwen2.5-VL / Gemini Vision) strictly as a bounded fallback/assist for difficult industrial layouts or diagrams while treating model outputs as untrusted proposals subject to downstream verification.
- Produce structured industrial outputs matching the unified schema (document_type: "industrial_hmi", tables such as coil_list, domain fields, and traceability metadata).

Technology Candidates from the Plan

- Image processing & layout/region detection: OpenCV.
- OCR & table structure: PaddleOCR, Tesseract, Table Transformer / OpenCV + OCR.
- Vision models (for difficult cases/layout interpretation): Qwen2.5-VL; Gemini Vision.
- Configuration & schemas: Pydantic + profile definitions.

Acceptance Criteria

- Routes General Vision vs. Industrial Vision benchmark images accurately and outputs valid schema payloads with document_type set appropriately (including industrial_hmi / coil_list examples).
- Preserves column alignment, industrial identifiers (such as coil IDs), and units/column associations on PLC/HMI and coil table test cases.
- Supports configurable per-factory profiles and a generic fallback parser without hardcoding a single factory layout.

Expected Deliverable
An Industrial Vision Module (src/engine/industrial/) plus Smart Image Router (src/engine/router.py), profile configuration examples, unit/integration tests, and Coil ID / field accuracy measurements on the industrial benchmark set.

## Phase P5: Validation & Confidence
Objective
Build the extraction validation, confidence scoring, anomaly detection, and human-in-the-loop review state layer so low-confidence, ambiguous, or inconsistent values are explicitly flagged and editable rather than silently guessed or hallucinated.

Scope and Boundaries

- In scope: Typed schema checks, required-field and range/consistency rules, unit and identifier format checks (such as confusable digits/IDs and coil/numeric ranges), field- and cell-level confidence aggregation, warning generation, and structured review/correction state transitions (extraction_status, uncertain field flags, manual override support with traceability).
- Out of scope: Rendering end-user web UI pages or REST/async API routes (handled in P7), generating final exported files (handled in P6), and full database/queue scaling if deferred (optional PostgreSQL/Redis).

Key Tasks and Steps

- Implement typed schema and domain validation rules using Pydantic and pluggable domain rule sets (covering numeric ranges, units, required fields, cross-field consistency, and confusable characters/digits in IDs).
- Compute granular confidence scores at cell/field/table levels and generate clear, actionable warnings whenever OCR/table confidence is low, units are missing/ambiguous, or values fail domain checks.
- Enforce a strict anti-hallucination rule: never invent missing values or silently overwrite uncertain extractions; mark uncertain fields for review and record manual corrections alongside original extracted values and source coordinates/traceability.
- Set extraction_status accurately (e.g., completed vs. needs review / partial / failed) based on validation outcomes and configured thresholds.
- Test validation and review/correction workflows on noisy, low-confidence, and error-injected benchmark cases.

Technology Candidates from the Plan

- Validation & typed models: Pydantic + domain rules.
- Optional persistence (if used for review state/history): PostgreSQL (or local structured state store).

Acceptance Criteria

- Low-confidence, ambiguous, or out-of-range fields and confusable IDs trigger explicit warnings and review flags instead of silent guessing.
- Manual corrections preserve traceability to the source region/cell and do not erase auditability of original values.
- All validation rules and edge cases are covered by automated unit and integration tests.

Expected Deliverable
A Validation & Review Module (src/engine/validation/) with Pydantic models, domain rule engine, confidence/warning logic, review/override API/service contracts, and comprehensive tests.

## Phase P6: Export Engine
Objective
Implement the multi-format export engine that generates clean, traceable outputs—XLSX, CSV, JSON, visual previews (JPEG/PNG), and PDF reports—from validated extraction results.

Scope and Boundaries

- In scope: Exporting structured extraction results and traceability/warning metadata to XLSX (formatted, filterable spreadsheets via OpenPyXL), CSV, JSON, annotated/preview images (JPEG/PNG), and PDF summary reports, reflecting manual corrections and exports metadata.
- Out of scope: Image preprocessing, OCR, table extraction, HMI parsing, core validation logic, and interactive web UI/API serving (handled in P1–P5 and P7).

Key Tasks and Steps

- Build the OpenPyXL Excel exporter generating formatted, filterable workbooks (e.g., summary/metadata, extracted tables with preserved columns/rows/units, and warnings/review notes where applicable).
- Implement JSON and CSV exporters that serialize the unified schema, tables, warnings, and traceability/review metadata cleanly and deterministically.
- Implement visual preview (JPEG/PNG) and PDF report generators showing extracted data, warnings, and source/bounding-box/cell traceability where available.
- Ensure exports reflect validated and manually corrected data accurately and update the output exports list/artifacts cleanly.
- Verify generated files against automated integrity tests (valid XLSX openability, parseable JSON/CSV, non-empty JPEG/PNG/PDF outputs, and accurate row/column/unit preservation).

Technology Candidates from the Plan

- Excel export: OpenPyXL (formatted, filterable spreadsheets).
- Image/preview handling: OpenCV / Python imaging utilities; Python standard/export libraries for JSON, CSV, and PDF report generation.

Acceptance Criteria

- Generates valid, readable XLSX, CSV, JSON, JPEG/PNG previews, and PDF reports from General Vision and Industrial Vision extraction outputs.
- Excel workbooks are properly formatted and filterable, preserving table columns, rows, and units without corrupting values.
- Traceability info (source coordinates/cells, warnings, and review status) is preserved in JSON/reports without breaking schema compatibility.

Expected Deliverable
An Export Module (src/engine/export/) supporting XLSX, CSV, JSON, JPEG/PNG previews, and PDF reports, complete with automated output-verification tests.

## Phase P7: API & Web Interface
Objective
Build the service layer with a Python + FastAPI backend and a usable web interface supporting single and batch image/PDF uploads, job status tracking, human review and manual editing of uncertain fields, and downloading exported files.

Scope and Boundaries

- In scope: RESTful API endpoints built with Python + FastAPI for uploading single or multiple images/PDFs, checking job/processing status, inspecting/editing extracted fields and tables during review, triggering exports, and downloading generated files; a functional web UI for upload, review/edit, and download; optional PostgreSQL and Redis integration for job history and background/batch queue processing.
- Out of scope: Rewriting core OCR/table/industrial/validation/export algorithms (consume P1–P6 modules), multi-tenant enterprise IAM/SSO unless specified, or full benchmark optimization sweeps (handled in P8).

Key Tasks and Steps

- Create the Python + FastAPI application exposing endpoints for single/batch file upload, job status polling, structured result retrieval, manual field/table edits with re-validation, and export downloads.
- Wire optional PostgreSQL (job/result persistence) and Redis (background/batch worker queue) behind clean configuration flags so the service can run locally with minimal setup or with full background queue persistence.
- Build a web interface allowing users to upload one or multiple images/PDFs, monitor processing status, view extracted tables and uncertain/flagged fields side-by-side with source images/previews, make manual corrections, and download XLSX, CSV, JSON, preview images, or PDF reports.
- Handle error responses, invalid file types, and batch progress cleanly without blocking the event loop on heavy CPU/GPU vision tasks.
- Write API and end-to-end workflow tests covering upload, classification/extraction, manual edit/review, and export download.

Technology Candidates from the Plan

- Backend & API: Python + FastAPI.
- Optional infrastructure: PostgreSQL (job history/results); Redis (background and batch processing).
- Core engine integration: P1–P6 modules (OpenCV, PaddleOCR, Tesseract, Docling, Table Transformer, Qwen2.5-VL / Gemini Vision, Pydantic, OpenPyXL).

Acceptance Criteria

- FastAPI endpoints support single and batch uploads, job status tracking, manual correction updates, and export downloads (XLSX, CSV, JSON, previews, PDF).
- Web interface enables a user to upload images, inspect/edit uncertain fields, and download results end-to-end on a local Linux machine.
- Optional PostgreSQL and Redis integrations work cleanly when enabled and degrade gracefully when omitted in lightweight local runs.

Expected Deliverable
A Service Layer & Web Interface (src/api/, src/web/, and configuration/deployment scripts) with API integration tests and end-to-end user workflow verification.

## Phase P8: Benchmark & Optimization
Objective
Execute a comprehensive, repeatable benchmark and optimization pass across all input categories on the target Linux environment—measuring accuracy, latency, and resource usage, tuning category-specific parameters/models, and verifying modular extensibility.

Scope and Boundaries

- In scope: Running repeatable benchmarks across the full labeled dataset (photographed documents/forms, dense multi-column small-font tables, computer/mobile screenshots, angled PLC/HMI screens, and coil tables with compact IDs, numbers, and units); measuring OCR CER, WER, Table Structure Accuracy, Field-level Accuracy, Coil ID Accuracy, and per-image/batch processing time plus CPU/GPU/memory usage; targeted tuning by category and verifying that adding a new image category does not require rewriting the full pipeline.
- Out of scope: Starting greenfield feature development unrelated to benchmark findings or making undocumented changes outside versioned configs/code.

Key Tasks and Steps

- Run a repeatable benchmark harness across all five dataset categories on a local Linux machine/server, recording OCR CER, WER, Table Structure Accuracy, Field-level Accuracy, Coil ID Accuracy, processing time per image and batch, and resource utilization.
- Compare candidate combinations where applicable (such as PaddleOCR vs. Tesseract, Table Transformer vs. OpenCV + OCR / Docling, and Qwen2.5-VL / Gemini Vision fallbacks) against concrete accuracy and latency trade-offs.
- Tune preprocessing parameters, OCR/table thresholds, industrial profiles, and validation/confidence rules by input category to address failure modes (small/blurry text, glare/angle, confusable IDs, dense tables) while keeping anti-hallucination safeguards intact.
- Test adding a new image category/profile to confirm modular extensibility without rewriting the core router, schema, validation, or export layers.
- Publish a clear Benchmark Report documenting methodology, metrics by category, hardware/resource profile, tuning changes, and remaining known limitations.

Technology Candidates from the Plan

- Full candidate stack under evaluation: OpenCV, PaddleOCR, Tesseract, Docling, Table Transformer, Qwen2.5-VL, Gemini Vision, Python + FastAPI, Pydantic, OpenPyXL, PostgreSQL, Redis on Linux.

Acceptance Criteria

- Every benchmark input category has repeatable automated evaluation scripts and documented accuracy (CER, WER, Table Structure Accuracy, Field-level Accuracy, Coil ID Accuracy) and latency/resource metrics.
- Category-specific tuning improves or documents trade-offs clearly without silently guessing low-confidence values or breaking the unified schema.
- Verified local Linux deployment readiness and documented extensibility for adding new image categories without rewriting the full pipeline.

Expected Deliverable
A Benchmark Report (docs/benchmarks/p8-benchmark-report.md) paired with reproducible benchmark runner scripts (benchmarks/), tuned configuration presets, and final verification logs.