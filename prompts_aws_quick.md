Image Extraction Engine: Implementation Prompts for Phases P0–P8

These nine prompts are based on the attached development plan Image_Extraction_Engine_Development_Plan_2_pkva.docx. Each one stands on its own, so you can give it to a coding agent without the others. Every prompt opens with a short shared context block, because the agent won't have seen the plan.

P0: Requirements & Data Specification

Context. You are working on the Image Extraction Engine, a "Modular Hybrid Vision Engine." It takes images and documents (JPG, PNG, WEBP, PDF, screenshots; single or batch), classifies the content, and sends it to one of two modules. General Vision handles documents, invoices, receipts, forms, tables, charts, screenshots and multi-page PDFs. Industrial Vision handles PLC/HMI screens, Hot/Cold Coil tables, coil IDs, thickness/width/weight/length, machine parameters, alarms and process diagrams. Both modules share a router, a unified output schema, a validation layer and an export layer. It must be deployable on a local Linux machine or server. No code exists yet. This is the first phase.

Objective. Write an approved, version-controlled specification that every later phase can build against: inputs, output schema, languages, privacy constraints, and a labeled benchmark dataset with its evaluation protocol.

Scope and boundaries.

In scope: requirements documents, JSON Schema / Pydantic model drafts, repository skeleton, dataset folder structure, labeling format and guidelines, metric definitions, and a small seed set of labeled samples.
Out of scope: any preprocessing, OCR, table or vision model code. Don't commit to final technology choices. Record them only as candidates to benchmark later.

Key tasks and steps.

Repository skeleton. Create a Python monorepo with engine/ (router/, preprocessing/, general/, industrial/, tables/, validation/, export/), service/, benchmark/, docs/, tests/. Add pyproject.toml (Python 3.11+), linting (ruff), typing (mypy), pytest and a basic CI config.
Input specification (docs/spec/inputs.md):
Supported formats and limits: max file size, max resolution, max PDF pages, max batch size.
Color modes and handling of corrupt or unsupported files.
Content categories. Define the taxonomy the router will output, for example:
General: document_scan, photo_document, invoice, receipt, form, table_image, chart, screenshot_desktop, screenshot_mobile, diagram, pdf_multipage.
Industrial: industrial_hmi, coil_table, machine_label, alarm_screen, process_diagram.
Fallback: unknown.
The taxonomy must be extensible without rewriting the pipeline. Specify a registration mechanism.
Unified output schema (engine/schema/). Write Pydantic v2 models plus an exported JSON Schema. Extend the plan's base shape: document_type, extraction_status, tables[] (with table_name, columns, rows, confidence), warnings, exports. Add:
job_id, source (file name, page, hash), pages[], text_blocks[] (text, bbox, reading order, confidence, language).
cells[] with row/col index, row/col span, bbox and confidence.
fields[]: name, value, raw_text, unit, type, confidence, bbox/cell reference, needs_review.
processing metadata: pipeline path, module versions, timings.
Domain-specific extensions via a namespaced extensions object, so the core structure never changes.
Industrial field dictionary. Define coil fields: ZONE, HOT_COIL_NO, COLD_COIL_NO, THICK, WIDTH, WEIGHT, LENGTH, product code. For each, give the expected type, unit, format regex placeholders and plausible ranges. Mark factory-specific values as configurable.
Language requirements. Vietnamese (with diacritics) and English text, digits, and alphanumeric product identifiers.
Privacy and security constraints. Local processing by default. Any external vision API (for example Gemini Vision) must be opt-in and configurable. Define data retention, logging redaction and access rules.
Benchmark dataset spec (benchmark/README.md):
Folder layout per category.
Ground-truth format: JSON matching the unified schema, plus plain-text transcripts for CER/WER.
Labeling guidelines and train/dev/test split policy.
Required categories: photographed documents/forms, dense small-font tables, desktop and mobile screenshots, angled photos of PLC/HMI screens, and coil tables with compact IDs, numbers and units.
Include real operating conditions such as blur, glare and skew, not only clean samples.
Metric definitions (docs/spec/metrics.md). Give exact formulas and normalization rules for:
OCR Character Error Rate (CER) and Word Error Rate (WER).
Table Structure Accuracy (for example TEDS or a cell-adjacency F1).
Field-level Accuracy.
Coil ID exact-match Accuracy.
Processing Time per image and per batch.
Seed data. Add about 5 labeled samples per category, or synthetic placeholders if real data isn't available, plus a validator script that checks every ground-truth file against the schema.
Priorities. Map requirements to MVP versus later, using the plan's priorities:
P0 must have: OCR + preprocessing, tables, validation, Excel/JSON export.
P1 high: HMI parser, configurable coil schema, confidence/review.
P2 medium: vision AI, web UI, API, batch.
P3 later: DB history, automation, analytics, integrations.

Technology candidates (to record, not commit). OpenCV; PaddleOCR and Tesseract; Docling; Table Transformer, or OpenCV + OCR; Qwen2.5-VL and Gemini Vision; Python + FastAPI; Pydantic + domain rules; OpenPyXL; PostgreSQL and Redis (optional).

Acceptance criteria.

The schema models import cleanly, export valid JSON Schema, and validate the plan's example payload.
Every seed ground-truth file passes the validator in CI.
The category taxonomy has a documented extension mechanism.
Every metric has a formula, normalization rules and a reference implementation stub with unit tests.
The privacy section states clearly that the default deployment is local-only.
Open questions are listed in docs/spec/open_questions.md for stakeholder sign-off.

Expected deliverable. An "Approved specification" package: the docs/spec/ documents, the schema package, the benchmark dataset skeleton with seed labels and validator, metric stubs and the repository skeleton with passing CI.

P1: Image Preprocessing

Context. The Image Extraction Engine is a modular hybrid vision engine with a General Vision module (documents, tables, screenshots, charts) and an Industrial Vision module (PLC/HMI screens, coil tables, machine parameters). They share a router, a unified Pydantic output schema, validation and export. It runs locally on Linux. P0 delivered the spec, schema, and benchmark dataset under benchmark/. This phase builds the preprocessing stage that every later stage relies on.

Objective. Build a configurable, deterministic image preprocessing pipeline: orientation correction, perspective correction, denoising, sharpening, contrast enhancement, cropping, and image-quality assessment. It must improve OCR quality without altering content.

Scope and boundaries.

In scope:
Loading every supported input (JPG, PNG, WEBP, PDF rasterized page by page, screenshots).
The individual transforms, a composable pipeline, quality scoring, and debug visual output.
A transform log that records the geometry so OCR coordinates can be mapped back to the original image.
Out of scope: OCR, table detection and classification. A simple quality-based routing hint is allowed.

Key tasks and steps.

Input loader (engine/preprocessing/io.py).
Decode images and rasterize PDFs at a configurable DPI (default 300), using pypdfium2 or PyMuPDF.
Normalize to RGB numpy arrays and compute a SHA-256 of the source.
Reject corrupt or unsupported files with typed errors.
Transforms. Make each transform a pure function with a config dataclass:
Orientation: detect 0/90/180/270 rotation (OCR-based angle classifier or text-line heuristics) and correct small skew via Hough lines or minAreaRect.
Perspective correction: detect document or screen boundaries (edge detection, contour approximation to a quadrilateral, largest-quad heuristics) and warp to a rectangle. This must work on monitors photographed at an angle.
Denoising: fastNlMeans and bilateral filtering, selectable.
Sharpening: unsharp mask with a bounded strength.
Contrast: CLAHE on the luminance channel, plus optional gamma.
Glare mitigation: detect saturated regions and flag them. Don't hallucinate pixels.
Cropping: trim borders, crop to the detected content or screen, and support a region-of-interest API for later multi-scale OCR.
Upscaling: for small text, configurable bicubic resizing (optional super-resolution hook).
Quality assessment. Compute blur (variance of Laplacian), brightness, contrast, glare ratio, skew angle, resolution and estimated text height. Return a QualityReport with warnings such as LOW_RESOLUTION, BLURRY and GLARE_DETECTED.
Pipeline orchestration.
A PreprocessingPipeline assembled from YAML profiles (general_document, screenshot, industrial_screen_photo).
Screenshots should skip perspective correction and denoising by default.
Output a PreprocessedImage with the image, the QualityReport and an ordered TransformLog.
Coordinate traceability. Store the homography and affine matrices in the log. Provide map_to_original(points) and map_to_processed(points), with round-trip error under 2 px.
Debug output. An optional side-by-side before/after PNG, plus an overlay of the detected quadrilateral.
Tests.
Unit tests per transform on synthetic images: rotated text, warped rectangles, added noise.
Golden tests on benchmark samples.
Property test confirming that screenshots pass through near-unchanged.
Mini-benchmark. A script in benchmark/ that runs a baseline OCR engine (Tesseract or PaddleOCR) on raw versus preprocessed images and reports the CER difference per category.

Technology candidates. OpenCV (core), NumPy, Pillow, pypdfium2/PyMuPDF for PDF rasterization; PaddleOCR's angle classifier or Tesseract OSD for orientation.

Acceptance criteria.

All supported formats load. Corrupt files produce typed errors, not crashes.
Skew is corrected within ±1° on synthetic tests. Perspective rectification succeeds on at least 90% of angled-screen benchmark samples where all four corners are visible.
Coordinate mapping round-trips within 2 px.
Preprocessing doesn't increase CER on any category (screenshots included) and reduces CER on photographed categories compared with raw input.
Low-quality inputs produce explicit warnings in the QualityReport.
Processing time is under 1 s per 12 MP image on CPU (record the real figure).
The pipeline is driven by profile configuration, so new profiles need no code changes.

Expected deliverable. The engine/preprocessing/ package (transforms, pipeline, quality report, coordinate mapping), YAML profiles, tests, debug visualization, and a short report (docs/reports/p1_preprocessing.md) with before/after CER results.

P2: General OCR

Context. The Image Extraction Engine is a modular hybrid vision engine: General Vision (documents, invoices, forms, screenshots, charts, multi-page PDFs) and Industrial Vision (PLC/HMI, coil tables). They share a router, a unified Pydantic schema (text_blocks, fields, tables, warnings, and so on), validation and export. Local Linux deployment. P0 delivered the spec and benchmark. P1 delivered engine/preprocessing/, which returns a PreprocessedImage with a QualityReport and a coordinate-mapping TransformLog.

Objective. Build the General OCR module. It extracts text from documents, screenshots and images in Vietnamese and English (including digits and product identifiers), keeps word and line coordinates, and reconstructs reading order, all through a pluggable OCR backend interface.

Scope and boundaries.

In scope:
OCR engine abstraction with at least two backends.
Line, word and block output with bounding boxes and confidences.
Reading-order reconstruction and multi-page PDF handling.
Use of the embedded PDF text layer when present.
Multi-scale re-OCR of low-confidence regions.
A first version of the Smart Image Router (General versus Industrial classification).
Out of scope: table structure reconstruction (P3), industrial parsing (P4), field validation (P5).

Key tasks and steps.

Backend interface (engine/ocr/base.py). Define OCREngine.recognize(image, lang, roi=None) -> list[OCRToken]. Each token carries text, polygon/bbox, confidence, language and level (word, line).
Backends.
PaddleOCR (multilingual model that supports Vietnamese and Latin).
Tesseract via pytesseract (vie+eng).
Both configurable. Make sure Vietnamese diacritics survive and Unicode is normalized to NFC.
Document parsing path. For PDFs and structured documents, integrate Docling to extract the native text layer and layout. Run OCR only on pages or regions without usable text.
Layout and reading order.
Group tokens into lines and blocks (clustering by baseline and spacing).
Detect multi-column layouts.
Order blocks top-to-bottom and left-to-right per column.
Assign a reading_order index to every block.
Coordinates. Map every bbox back to original-image coordinates using the P1 TransformLog, and store both the processed and the original coordinates.
Multi-scale refinement. For tokens below a confidence threshold or with small text height, crop the region, upscale it, re-OCR it and keep the best result. Record the attempts in metadata.
Optional ensemble. A configurable strategy that runs both engines and picks per line by confidence and a lexicon or regex. Disabled by default and benchmarked.
Smart Image Router v1 (engine/router/).
A classifier that predicts the P0 taxonomy categories from image features, OCR keyword cues (for example "COIL", "ALARM", "THICK", HMI color patterns) and quality metrics. Rules first, with a hook for an ML classifier.
Output a category, a confidence and a pipeline route. Categories register through a plugin registry.
Screenshot and chart handling. Tune for crisp UI text by skipping denoising and handling light and dark themes. For charts, extract titles, axis labels and legends as labeled text blocks. Leave full chart data extraction as a vision-model extension hook.
Schema output. Populate text_blocks, pages and processing metadata in the unified schema.
Evaluation. Benchmark scripts that compute CER/WER per category and per engine, latency, and router accuracy as a confusion matrix.

Technology candidates. PaddleOCR; Tesseract; Docling (PDF/document structure); OpenCV for region handling; Qwen2.5-VL or Gemini Vision only as an optional extension hook for difficult cases, not on the default path.

Acceptance criteria.

Both OCR backends run behind the same interface and can be switched by configuration.
Vietnamese diacritics are preserved. CER and WER are reported per category and per engine on the benchmark test split.
Every text block has a bbox in original coordinates, a confidence and a reading-order index.
Multi-column documents are read in the correct order on at least 90% of benchmark multi-column pages.
Native PDF text is used when it exists, and OCR runs only where needed.
Low-confidence tokens are flagged, never silently "corrected."
Router accuracy is reported, and a new category can be added by registering a plugin without changing core code.

Expected deliverable. The engine/ocr/ and engine/router/ packages, backend adapters, a Docling integration, tests, and a benchmark report (docs/reports/p2_ocr.md) comparing PaddleOCR and Tesseract on CER, WER and latency, with a recommended default.

P3: Table Extraction

Context. The Image Extraction Engine is a modular hybrid vision engine with General Vision and Industrial Vision modules behind a shared router, a unified Pydantic schema (tables[] with table_name, columns, rows, confidence, cell data), validation and export. Local Linux deployment. Already available: P1 preprocessing (PreprocessedImage plus coordinate mapping) and P2 OCR (tokens with bboxes, confidence and reading order) with a router.

Objective. Build a table extraction module. It detects tables, reconstructs rows, columns and cells (including spans and headers), assigns OCR text to cells, and keeps cell positions for traceability. It must handle dense, small-font, many-column tables, including industrial coil lists.

Scope and boundaries.

In scope: table detection, structure recognition (bordered and borderless), cell–text assignment, header detection, merged cells, multi-page tables, and output to the unified schema.
Out of scope:
Domain field semantics and units, which come in P4.
Validation rules, which come in P5.
Exporting files, which comes in P6. A debug CSV dump is fine.

Key tasks and steps.

Detection interface (engine/tables/detect.py). TableDetector.detect(image) -> list[TableRegion], where each region has a bbox and a confidence.
Structure recognition, with two backends:
Table Transformer (detection and structure models) for complex or borderless tables.
OpenCV + OCR for ruled tables: morphological line extraction, line intersections, a cell grid. For borderless tables, cluster OCR token x-coordinates into columns and y-coordinates into rows.
Make the backend selectable per profile, with a hybrid mode that reconciles the two.
Cell assignment. Assign OCR tokens to cells by bbox overlap. Handle tokens that straddle a boundary and multi-line cells. Re-OCR individual cell crops when confidence is low (the P2 multi-scale hook).
Headers and spans. Detect header rows (position, styling, text cues), multi-level headers, and row/col spans. Produce columns as ordered header names, with stable normalized keys (for example HOT_COIL_NO).
Column alignment integrity. Never shift values between columns. Empty cells stay explicitly empty (null with a reason), never filled with neighboring values.
Multi-page and continuation. Merge tables that continue across PDF pages when the headers match.
Output. Populate tables[] with table_name, columns, rows (list of dicts keyed by column), cells[] (row, col, spans, text, bbox in original coordinates, confidence) and a table-level confidence.
Debug visualization. Overlay the detected grid and cell IDs on the image.
Evaluation.
Table Structure Accuracy (the TEDS or cell-adjacency metric from P0) and cell-content accuracy.
Reported separately for ruled, borderless, dense small-font and coil tables, with latency per table.
Compare the backends and the hybrid mode.

Technology candidates. Table Transformer (Microsoft TATR); OpenCV + OCR (PaddleOCR or Tesseract from P2); Docling table output for native PDFs as a third comparison source.

Acceptance criteria.

Detection recall of at least 95% on benchmark table images (record the actual figure).
Structure accuracy is reported per table type, and the hybrid mode is at least as good as the best single backend on dense tables.
Every cell value traces back to its cell bbox in original-image coordinates.
No silent column shifts: a regression test suite of coil tables checks that every value stays in its correct column.
Empty and uncertain cells are explicitly marked and get warnings.
The backend can be switched by configuration.

Expected deliverable. The engine/tables/ package (detectors, structure backends, cell assignment, header logic), visual debug tools, tests and docs/reports/p3_tables.md with structure-accuracy results and a recommended default per table type.

P4: Industrial Vision

Context. The Image Extraction Engine is a modular hybrid vision engine. General Vision is now in place: preprocessing (P1), OCR plus router (P2), tables (P3). They share a unified Pydantic schema, validation and export layers. Local Linux deployment. This phase builds the separate Industrial Vision module for PLC/HMI control screens, industrial dashboards, Hot Coil / Cold Coil tables and production lists, product codes and coil IDs, thickness/width/weight/length, machine parameters, alarms, operating states and process diagrams. Column alignment and units are critical here.

Objective. Build the Industrial Vision pipeline: screen-region detection, OCR tuned for compact labels and digits, industrial table parsing, extraction of value/unit/label, alarms and states, and configurable per-factory machine profiles with a generic fallback parser.

Scope and boundaries.

In scope:
Screen/monitor geometry normalization (building on P1).
HMI region segmentation.
Digit- and ID-optimized OCR.
Coil table parsing (reusing P3).
Label–value–unit pairing, alarm and state detection.
Profile system (YAML), generic fallback.
Router integration for industrial categories.
Out of scope:
Full validation and review UI (P5). This phase only provides the format rules per field.
Exports (P6).
Comparing data across images or time points (an advanced capability, designed only as a hook).

Key tasks and steps.

Module isolation. Create engine/industrial/ as its own module behind the shared router interface. It must not modify General Vision code. It may only reuse shared components through public interfaces.
Screen normalization. Detect monitor bezels or screen boundaries, rectify perspective, and normalize the aspect ratio. Detect moiré and glare and turn them into warnings.
Region detection. Segment the HMI into panels, tables, label/value boxes, alarm banners and status indicators, using contours and color segmentation (typical HMI palettes, alarm red/yellow). Add an optional detector-model hook.
Compact OCR. Configure the OCR for short alphanumeric strings and digits:
Character whitelists per field type.
Upscaled region crops.
Seven-segment and LCD-style digit handling if present.
Recording of the top-k alternatives for confusable characters (0/O, 1/I/l, 5/S, 8/B).
Coil table parsing. Use the P3 table module, then map headers to canonical fields (ZONE, HOT_COIL_NO, COLD_COIL_NO, THICK, WIDTH, WEIGHT, LENGTH, product code) using profile aliases, including Vietnamese and abbreviated header variants. Keep row and column associations exact.
Value–unit extraction. Parse numbers (decimal and thousands separators), split out units (mm, m, kg, t, °C, bar, rpm, %, and others), and link each value to its label or column. Keep the raw text, the parsed value and the unit together.
Alarms and states. Extract alarm messages, codes, timestamps, severity (by color or keyword) and operating states (RUN, STOP, AUTO, MANUAL, FAULT, and similar).
Profile system (profiles/*.yaml). Each factory/machine profile defines:
Matching cues: title text, layout anchors, colors.
Region templates (relative coordinates).
Field definitions: name, aliases, type, unit, regex format such as a coil ID pattern, plausible range.
Table schemas.
Load profiles at runtime. A new factory is added without code changes.
Generic fallback parser. When no profile matches, extract all label–value–unit pairs and tables generically, and set document_type: industrial_hmi with a NO_PROFILE_MATCHED warning.
Router integration. Register industrial categories (industrial_hmi, coil_table, machine_label, alarm_screen, process_diagram) and their routing cues.
Optional vision-model assist. An interface to query Qwen2.5-VL (local) or Gemini Vision (opt-in, external) for layout interpretation of hard screens. Its output is a proposal only and must match OCR text or source pixels before it is accepted. It must never invent values.
Evaluation. Coil ID exact-match accuracy, field-level accuracy, unit-association accuracy and latency, on angled-photo HMI and coil-table benchmark sets.

Technology candidates. OpenCV (screen detection, color segmentation, rectification); PaddleOCR / Tesseract (with whitelists); Table Transformer or OpenCV + OCR (from P3); Qwen2.5-VL and Gemini Vision (optional assist); Pydantic for profile and field models; PyYAML for profiles.

Acceptance criteria.

General Vision and Industrial Vision run as separate modules through the shared router and schema.
Every numeric industrial value keeps its unit and its column/label association, verified by regression tests.
Coil ID exact-match accuracy is reported. Ambiguous characters are flagged with alternatives, not guessed.
Adding a new factory profile requires only a YAML file, shown with at least two sample profiles plus the generic fallback.
Angled-photo HMI benchmark images are rectified and parsed. Failures produce explicit warnings.
Vision-model output is never accepted without OCR or pixel corroboration, verified by tests.

Expected deliverable. The engine/industrial/ package (screen normalization, region detection, compact OCR, coil table mapping, value/unit/alarm extraction, profile loader, fallback parser), sample profiles, tests and docs/reports/p4_industrial.md with Coil ID and field accuracy results.


P5: Validation & Confidence

Context. The Image Extraction Engine is a modular hybrid vision engine. Preprocessing (P1), OCR plus router (P2), tables (P3) and Industrial Vision with YAML profiles (P4) all produce results in a unified Pydantic schema (text_blocks, tables, cells, fields, warnings, confidence). Local Linux deployment. A core principle: low-confidence or ambiguous values must be flagged for review, never silently guessed, and AI output is a proposal, never truth.

Objective. Build the extraction-and-validation layer: normalize fields, run typed schema checks and domain rules, compute calibrated field-level confidence, detect anomalies, and support a human-in-the-loop review workflow with an audit trail.

Scope and boundaries.

In scope:
Normalization, Pydantic validation and domain rule engine.
Confidence aggregation and calibration, anomaly flags.
Review queue data model and correction API (library level), audit trail.
Out of scope:
The web review UI (P7). This phase exposes the backend functions and data model the UI will use.
Exports (P6).

Key tasks and steps.

Normalization (engine/validation/normalize.py):
Unicode NFC, whitespace cleanup.
Locale-aware numbers (Vietnamese 1.234,5 versus English 1,234.5, configurable per profile).
Dates, unit canonicalization (t ↔ kg, mm ↔ m) that keeps the original unit.
Keep raw_text alongside the normalized value.
Schema validation. Generate Pydantic models dynamically from P4 profile field definitions and P0 schemas: required fields, types, regex formats such as the coil ID pattern, and enums for states.
Domain rule engine. Declarative rules in YAML:
Ranges (for example a THICK plausible range).
Cross-field consistency (for example weight ≈ f(thickness, width, length, density) within a tolerance).
Uniqueness of coil IDs within a table, checksum or format rules.
Row-count consistency and units matching their columns.
Each rule has an ID, a severity (error/warning/info) and a message.
Confidence model.
Combine OCR token confidence, multi-scale and ensemble agreement, table-cell confidence, rule results and image-quality signals into a 0–1 field confidence.
Aggregate up to table and document level.
Calibrate on the benchmark dev split (isotonic or Platt) and report a reliability diagram.
Ambiguity handling.
Confusable characters with OCR alternatives: try candidates against format rules. If exactly one passes, propose it with needs_review=true and record the reason. If zero or several pass, flag the field and don't choose.
Missing values stay null with a reason, never imputed.
Anomaly flags. Outliers against the table's column distribution, duplicate rows, unit mismatches, impossible values, and vision-model output that contradicts OCR.
Review workflow (backend).
ReviewItem model: field ref, value, alternatives, confidence, reasons, crop/bbox for display.
Functions to list pending items, accept, correct or reject a value, and re-run validation after edits.
Configurable thresholds per field and profile decide auto-accept versus review.
Audit trail. An immutable log of every correction: who, when, old value, new value, reason. Corrected results are versioned. Persist to files by default, with a repository interface ready for PostgreSQL later.
Output. Every field and cell gets confidence, needs_review, validation_results[] and warnings[]. extraction_status becomes one of completed, completed_with_warnings, needs_review or failed.
Evaluation. The share of real errors caught (flagged) versus false alarms, field-level accuracy after auto-accept, and the review rate at different thresholds.

Technology candidates. Pydantic v2 + domain rules; PyYAML for rule definitions; scikit-learn (optional) for calibration; optional PostgreSQL for audit persistence.

Acceptance criteria.

No silent guessing: tests confirm that ambiguous or missing values are flagged and never auto-filled.
Every validated field carries confidence, rule results and traceability to its source bbox or cell.
Rules and thresholds are configurable per profile without code changes.
Error-catching (recall) of at least 95% on benchmark fields with known wrong values, with the review rate reported at that threshold.
The confidence calibration error (ECE) is reported on the test split.
Corrections are fully audited, and re-validation after an edit updates the status correctly.

Expected deliverable. The engine/validation/ package (normalization, dynamic schemas, rule engine, confidence model, anomaly detection, review backend, audit trail), sample rule files, tests and docs/reports/p5_validation.md covering calibration and the threshold trade-offs.

P6: Export Engine

Context. The Image Extraction Engine is a modular hybrid vision engine. Its General Vision and Industrial Vision modules produce validated results in a unified Pydantic schema. P5 added field confidence, needs_review flags, warnings and an audit trail, and every value traces back to a source bbox or table cell. Local Linux deployment.

Objective. Build an export layer that turns validated results into XLSX, CSV, JSON, annotated JPEG/PNG previews and PDF reports, with full traceability from each exported value back to its source location, confidence and review status.

Scope and boundaries.

In scope:
A pluggable exporter interface and the five formats.
Formatting, traceability metadata, multi-table and multi-page handling, batch and combined exports.
Deterministic output.
Out of scope: API endpoints and download UI (P7), and downstream integrations, which are only an extension point.

Key tasks and steps.

Exporter interface (engine/export/base.py). Exporter.export(result, options) -> ExportArtifact (path, MIME type, checksum). Use a registry so new formats plug in without core changes.
XLSX (OpenPyXL).
One sheet per table, plus a Summary sheet (document type, status, warnings) and a Traceability sheet (cell ref → source page, bbox, confidence, review status, correction history ID).
Formatting: frozen header row, auto-filter, column widths, numeric cell types with number formats (don't store numbers as text), and units in headers or separate unit columns.
Conditional fill for low-confidence and needs-review cells, with cell comments giving the reason.
CSV. One file per table, UTF-8 with BOM option for Excel Vietnamese compatibility, configurable delimiter and decimal separator. Optional sidecar *_meta.csv with confidence and traceability.
JSON. The full unified schema payload, validated against the P0 JSON Schema before writing, with an option for "values only" versus "full with provenance."
Image previews (JPEG/PNG). Overlay extracted table grids, field bboxes and color-coded confidence (green/amber/red) on the original image, with a legend. Optional per-field crop thumbnails.
PDF report. A cover with job metadata, per-page annotated preview, extracted tables, a warnings and review summary, and a validation rules overview. Use ReportLab or HTML-to-PDF.
Batch exports. Combined XLSX (one sheet per source or a merged table with a source_file column), plus a ZIP bundle with a manifest.
Traceability guarantee. Every exported value carries, or links to, its source location and confidence. Write a manifest JSON listing the artifacts, checksums, engine/module versions and profile used.
Determinism and tests.
Same input gives byte-stable JSON/CSV (ignoring timestamps behind a flag).
Round-trip test: re-read the XLSX/CSV and compare with the source result.
Tests for Vietnamese characters, large tables (≥ 1,000 rows), empty and null cells, and the export of corrected values.

Technology candidates. OpenPyXL (Excel); Python csv/pandas; Pydantic JSON serialization; OpenCV/Pillow for previews; ReportLab (or WeasyPrint) for PDF reports.

Acceptance criteria.

All five formats are generated from a single validated result, and from a batch.
XLSX opens in Excel and LibreOffice without repair prompts, numbers are numeric, headers are filterable, and low-confidence cells are highlighted with reasons.
JSON validates against the unified JSON Schema.
Round-trip tests pass with no value, unit or column drift.
Every exported value can be traced to its source page, bbox or cell, and its confidence.
Adding a new export format needs only a new registered exporter.

Expected deliverable. The engine/export/ package with XLSX, CSV, JSON, image preview and PDF report exporters, a batch bundler, a manifest, sample outputs generated from benchmark samples (docs/samples/exports/), and tests.

P7: API & Web Interface

Context. The Image Extraction Engine is a modular hybrid vision engine. Built so far: preprocessing (P1), OCR plus Smart Image Router (P2), tables (P3), Industrial Vision with profiles (P4), validation/confidence/review backend with audit trail (P5), and exports in XLSX, CSV, JSON, previews and PDF (P6). It must deploy on a local Linux machine or server, with local processing by default.

Objective. Make the engine usable through a Python/FastAPI service and a web interface that covers: upload single or batch images, track job status, review and edit flagged values side by side with the source image, and download exports. Add API integration for external systems.

Scope and boundaries.

In scope:
REST API, an asynchronous job system, the web UI (upload, jobs, review/edit, download).
Authentication (simple, local), configuration, Docker deployment, OpenAPI docs.
Optional PostgreSQL for job history and Redis for queues, with a no-dependency fallback mode.
Out of scope: advanced analytics, multi-tenant SaaS features and third-party integrations beyond webhooks.

Key tasks and steps.

Service layout. service/api/ (FastAPI), service/worker/, service/web/.
Job model. Job (id, status queued|processing|needs_review|completed|failed, files, profile, options, timestamps, progress, errors) and JobFile with per-file result references.
API endpoints (v1).
POST /v1/jobs: multipart upload of one or more files, plus options (profile, forced category, languages, export formats).
GET /v1/jobs/{id}: status and progress.
GET /v1/jobs/{id}/result: unified JSON.
GET /v1/jobs/{id}/review: pending review items.
PATCH /v1/jobs/{id}/fields/{field_id}: accept, correct or reject. Triggers re-validation and an audit log entry.
POST /v1/jobs/{id}/exports, then GET /v1/jobs/{id}/exports/{format}: download.
GET /v1/profiles, GET /v1/health, GET /v1/version.
Optional webhook callback on completion.
Async processing. Background workers with Redis (RQ, Celery or arq) for batch and long jobs. Fallback: an in-process worker pool and SQLite when Redis or PostgreSQL aren't configured. Add retries, timeouts and cancellation.
Persistence. A repository layer with SQLite (default) and PostgreSQL (optional) backends via SQLAlchemy, plus Alembic migrations. Configurable file storage on the local filesystem.
Security and limits.
API key or basic auth, upload size and type validation, rate limiting.
Configurable retention and cleanup.
External vision APIs off by default, enabled only via config, with a visible indicator in the UI when in use.
Web UI (React + TypeScript, or a lightweight server-rendered alternative):
Upload page: drag-and-drop, batch, profile selection.
Jobs list: live status updates via polling or SSE.
Review/edit view: source image with bbox overlays and zoom. Click a field or cell to see its crop, OCR alternatives, confidence and reasons. Edit inline, accept or reject, and use keyboard shortcuts to move to the next flagged item. Correct table cells in a grid synced to the image.
Results and download page with format choices.
UI text in English with i18n support for Vietnamese.
Deployment. Dockerfiles and docker-compose (api, worker, optional redis and postgres), a GPU-optional configuration, environment-based settings and a README for local Linux installation.
Tests. API tests (pytest + httpx), worker integration tests, end-to-end UI tests (Playwright) covering upload → review → correct → export, and a load smoke test for batch uploads.

Technology candidates. Python + FastAPI; Pydantic for request and response models; Redis (optional queue); PostgreSQL (optional history) with SQLite fallback; SQLAlchemy/Alembic; React/TypeScript for the UI; Docker.

Acceptance criteria.

A user can upload single and batch files, watch progress, review and correct every flagged value next to its source crop, and download XLSX and JSON (plus CSV, preview and PDF), all from the browser.
Every API endpoint is documented in auto-generated OpenAPI, and the request/response models match the unified schema.
Corrections create audit entries and update the exported results.
It runs fully offline on a local Linux machine with docker compose up, and in a minimal mode without Redis or PostgreSQL.
Batch jobs run asynchronously without blocking the API. Failures surface clear errors per file.
The end-to-end test suite passes in CI.

Expected deliverable. A usable interface: the FastAPI service, worker, web UI, persistence layer, Docker deployment, OpenAPI docs, user guide (docs/user_guide.md) and passing API and end-to-end tests.

P8: Benchmark & Optimization

Context. The Image Extraction Engine is a complete modular hybrid vision engine: preprocessing, OCR plus router, tables, Industrial Vision with profiles, validation/review, exports, and API/web UI (P1–P7). A labeled benchmark dataset and metric definitions came from P0. It contains photographed documents and forms, dense small-font tables, desktop and mobile screenshots, angled PLC/HMI photos, and coil tables. Technology choices so far are candidates and must be confirmed against data.

Objective. Measure quality, speed, resource use and robustness for every input category in a repeatable way. Tune the pipeline per category, settle the technology selections based on evidence, and publish a benchmark report with documented accuracy.

Scope and boundaries.

In scope:
A reproducible benchmark harness and metric computation.
Comparisons between candidate engines, robustness and stress tests.
Profiling and optimization, per-category tuning, regression gating in CI.
The final report.
Out of scope: new product features. You may change configuration and fix performance issues, but not functional scope.

Key tasks and steps.

Harness (benchmark/run.py).
Runs the full pipeline on a dataset split.
Writes predictions in the unified schema and computes every metric.
Saves versioned run artifacts: config, git SHA, hardware info, model versions.
Supports filtering by category and by pipeline variant.
Metrics. OCR CER, WER, Table Structure Accuracy, Field-level Accuracy, Coil ID exact-match Accuracy, and Processing Time per image and per batch. Add router accuracy, the error-catch rate and review rate from P5, and confidence calibration (ECE). Report all of them per category, with confidence intervals via bootstrap.
Candidate comparison matrix. For each category, compare:
PaddleOCR vs Tesseract vs the ensemble.
Table Transformer vs OpenCV + OCR vs hybrid vs Docling (for PDFs).
With and without the vision-model assist (Qwen2.5-VL local, Gemini Vision opt-in). Measure the accuracy gain, the hallucination or altered-value rate, latency and cost.
Preprocessing profiles: on, off, and per-transform ablations.
Robustness tests. Synthetic perturbations at increasing strength: blur, glare, perspective angle, JPEG compression, low resolution, rotation, moiré. Plot accuracy against severity and find where quality breaks down.
Performance and resources.
Measure latency (p50/p95), throughput for batches, CPU/GPU usage, peak RAM/VRAM and model load time, on a reference local Linux machine (CPU-only and GPU).
Profile hotspots with py-spy or cProfile.
Optimization.
Model warm-up and caching, batching of OCR crops, resolution caps per category.
Skipping unnecessary steps (for example denoising on screenshots), parallel page processing.
Optional ONNX/TensorRT or quantization where supported.
Confirm that accuracy doesn't regress after each optimization.
Per-category tuning. Tune thresholds (OCR confidence, review threshold, table detection), preprocessing profiles and engine choice per category on the dev split only. Record the final values in versioned config files, then evaluate once on the test split.
Error analysis. Group failures by root cause (preprocessing, OCR, structure, mapping, validation), with sample images, and propose follow-up work.
Regression gating. A CI job that runs a fast benchmark subset and fails when key metrics drop below thresholds or latency regresses beyond a tolerance.
Report. docs/reports/benchmark_report.md, plus HTML/PDF with charts.

Technology candidates. Everything from the plan under evaluation: OpenCV; PaddleOCR; Tesseract; Docling; Table Transformer; OpenCV + OCR; Qwen2.5-VL; Gemini Vision; FastAPI service under load; Pydantic validation; OpenPyXL export timing; PostgreSQL/Redis under batch load. Add tooling: jiwer (CER/WER), pandas/matplotlib (analysis and charts), py-spy, locust (API load testing).

Acceptance criteria.

Every input category has a repeatable benchmark (one command, fixed seed, versioned data) and documented accuracy for every applicable metric.
Final technology selections per category are justified by the comparison data, with trade-offs stated.
Vision-model assist has a measured altered-value rate, and the default configuration has zero accepted hallucinated values on the test set.
Optimized configurations meet or beat the pre-optimization accuracy, with documented latency and resource gains.
The robustness breakdown points are documented and tied to quality warnings in the product.
The CI regression gate is active.

Expected deliverable. A benchmark report (Markdown plus HTML/PDF with charts) covering per-category accuracy, the candidate comparison, robustness curves, performance and resource figures, the tuned configurations, error analysis and recommendations. Also: the reproducible benchmark/ harness, versioned tuned configs and the CI regression job.

Notes on decisions I made:

Added detail. I filled in specifics the plan doesn't state, such as directory names, endpoint names, numeric targets (for example ≥95% table recall, ±1° skew) and extra tools (pypdfium2, jiwer, locust). Change any target that doesn't match your requirements.
MVP priority. The plan marks the web UI, API and batch processing as medium priority, so P7 may come after the core features are stable.
Candidates stay open. All technology choices are treated as candidates until P8 settles them, as the plan intends.
