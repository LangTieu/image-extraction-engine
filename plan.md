IMAGE EXTRACTION ENGINE
DEVELOPMENT PLAN
Modular Hybrid Vision Engine
Purpose: define product scope, architecture, roadmap, technology candidates, and acceptance criteria. This is a plan only; no software has been built or deployed.
1. Product Objective
Build a modular image-understanding and extraction engine that accepts images and documents, classifies content, selects an appropriate processing path, extracts structured information, validates results, and exports reusable data.
1.1 General Vision
Photographed/scanned documents, invoices, receipts, and forms.
Tables, charts, reports, and website/application screenshots.
Text, labels, diagrams, and object descriptions.
Multi-page PDF documents.
1.2 Industrial Vision
PLC/HMI control screens and industrial dashboards.
Hot Coil / Cold Coil tables and production lists.
Product codes, coil IDs, thickness, width, weight, and length.
Machine parameters, alarms, operating states, and process diagrams.
Industrial layouts where column alignment and units matter.
2. Proposed System Architecture
3. Technology Candidates
Candidates for evaluation, not final selections. Benchmark against representative images before committing.
4. Development Roadmap
5. Unified Output Data Model
All processing paths should return a shared intermediate schema. Domain-specific fields can be added without changing the overall response structure.
{
  "document_type": "industrial_hmi",
  "extraction_status": "completed",
  "tables": [{
    "table_name": "coil_list",
    "columns": ["ZONE", "HOT_COIL_NO", "THICK", "WIDTH", "WEIGHT"],
    "rows": [],
    "confidence": 0.95
  }],
  "warnings": [],
  "exports": ["xlsx", "csv", "json", "jpg"]
}
6. MVP Scope
Upload one or multiple images.
Automatically classify general/document images versus industrial screens.
OCR for Vietnamese and English text, digits, and product identifiers.
Extract tables while preserving row and column structure.
Show uncertain fields and allow manual correction.
Export validated results to Excel and JSON.
7. Advanced Capabilities
Specialized PLC/HMI parser and per-factory configurable profiles.
Perspective correction and screen/monitor geometry normalization.
Compare extracted data across multiple images or time points.
Batch processing, API access, and asynchronous jobs.
Human-in-the-loop review and audit trail.
Additional export formats and downstream integrations.
8. Test Dataset & Evaluation
Create a labeled benchmark set that represents real operating conditions, not only clean sample images.
Photographed documents and forms.
Dense tables with many columns and small fonts.
Computer and mobile screenshots.
Industrial PLC/HMI screens photographed at an angle.
Coil tables with compact identifiers, numeric values, and units.
9. Priorities
10. Acceptance Criteria
One engine supports General Vision and Industrial Vision through separate modules.
New image categories can be added without rewriting the full pipeline.
Extracted values retain source location or table-cell traceability where possible.
Low-confidence or ambiguous values are flagged for review, not silently guessed.
Industrial numeric values retain units and column associations.
Each input category has a repeatable benchmark and documented accuracy.
Design supports deployment on a local Linux machine or server.
11. Key Risks & Mitigations
12. Recommended Direction
Adopt a Modular Hybrid Vision Engine: combine traditional OCR, computer vision, document/table parsers, and optional vision-language models. Keep General Vision and Industrial Vision as separate processing modules behind a shared router, schema, validation layer, and export interface. This reduces dependence on a single model and supports local deployment, cost control, and domain-specific accuracy tuning.
Scope note: This is a planning document only. No source code, project repository, or deployed system is included.
GENERAL VISION | INDUSTRIAL VISION
Documents • Tables • Screenshots • Charts | PLC/HMI • Coil Data • Machine Parameters
Layer | Responsibility
Input Layer | JPG, PNG, WEBP, PDF, screenshots; single and batch uploads.
Smart Image Router | Classify content and route to General Vision or Industrial Vision.
General Vision Pipeline | OCR, document parsing, table detection, chart/screenshot interpretation, object and diagram analysis.
Industrial Vision Pipeline | Screen-region detection, OCR for compact labels/digits, table parsing, configurable industrial profiles.
Extraction & Validation | Normalize fields, preserve row/column relationships, validate types/units, attach confidence and warnings.
Export Layer | XLSX, CSV, JSON, JPEG/PNG previews, and PDF reports.
Service Layer | Python/FastAPI API, web interface, optional database and background queue.
Area | Candidates | Purpose
Image processing | OpenCV | Perspective correction, denoising, cropping, contrast, region detection.
OCR | PaddleOCR; Tesseract | Text and numeric recognition; compare language and image-quality performance.
Document parsing | Docling | Document structure and PDF-oriented extraction.
Table recognition | Table Transformer; OpenCV + OCR | Rows, columns, cell boundaries, and table reconstruction.
Vision models | Qwen2.5-VL; Gemini Vision | Visual reasoning, layout interpretation, difficult cases.
Backend | Python + FastAPI | Processing services and API.
Validation | Pydantic + domain rules | Typed schemas, required fields, ranges, and consistency checks.
Excel export | OpenPyXL | Formatted, filterable spreadsheets.
Optional infrastructure | PostgreSQL; Redis | Job history/results; background and batch processing.
Phase | Workstream | Main activities | Deliverable
P0 | Requirements & data specification | Define inputs, output schema, languages, privacy constraints, benchmark dataset. | Approved specification
P1 | Image preprocessing | Orientation, perspective correction, denoising, sharpening, contrast, cropping. | Preprocessing pipeline
P2 | General OCR | Extract text from documents, screenshots, and images; preserve coordinates and reading order. | General OCR module
P3 | Table extraction | Detect tables, reconstruct rows/columns, retain cell positions. | Table extraction module
P4 | Industrial Vision | Parse PLC/HMI, coil tables, labels, values, units, alarms, machine profiles. | Industrial module
P5 | Validation & confidence | Field-level confidence, schema checks, anomaly flags, human review. | Validation/review module
P6 | Export engine | Generate XLSX, CSV, JSON, image/PDF previews with traceability. | Export module
P7 | API & web interface | Upload, job status, review/edit, download, API integration. | Usable interface
P8 | Benchmark & optimization | Measure quality, speed, resource use, robustness; tune by category. | Benchmark report
Metric | What it measures
OCR Character Error Rate (CER) | Character-level recognition quality.
Word Error Rate (WER) | Word-level recognition quality.
Table Structure Accuracy | Correct row, column, and cell reconstruction.
Field-level Accuracy | Correctness of each extracted business field.
Coil ID Accuracy | Exact match rate for hot/cold coil identifiers.
Processing Time | Latency per image and per batch.
Priority | Scope
P0 – Must have | OCR + preprocessing; table extraction; data validation; Excel/JSON export.
P1 – High | Industrial HMI parser; configurable coil schema; confidence and manual review.
P2 – Medium | Vision AI integration; web UI; API; batch processing.
P3 – Later | Database-backed history, automation, advanced analytics, integrations.
Risk | Mitigation
Small or blurred text | Preprocess, crop regions, use multi-scale OCR, flag low confidence.
Perspective distortion / glare | Detect screen boundaries, rectify perspective, assess image quality.
Confusable digits and IDs | Use domain validation, format constraints, and human confirmation.
Incorrect table structure | Combine table detection with OCR coordinates and cell-level review.
AI hallucination or altered values | Treat model output as a proposal; validate against source pixels; never invent missing values.
Factory-specific layouts | Use configurable profiles and a generic fallback parser.