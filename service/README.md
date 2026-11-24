# service/ (P7 — not started)

This package will hold the FastAPI application: job upload, progress
endpoints, result retrieval and XLSX/JSON downloads, plus the local-only
default binding and opt-in external-API configuration gate described in
`docs/spec/privacy.md`.

P0 delivers the contract it will serve: `engine.schema.ExtractionResult`
and `docs/spec/schema_v0.json`.
