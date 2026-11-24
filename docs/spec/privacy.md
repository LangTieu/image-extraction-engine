# Privacy & Security Constraints (P0)

## Default deployment is local-only

**The engine runs entirely on the local Linux machine or server by default.
No image, text, field value or metadata leaves the machine.** All processing
(OCR, tables, validation, export) uses local libraries and local models.

## External vision APIs are opt-in

Any external vision service (for example Gemini Vision) is:

- **Off by default.** Enabled only by explicit configuration
  (`privacy.allow_external_apis: true` plus the specific provider entry).
- Configurable per deployment and per job; a job without the opt-in flag is
  never sent outside.
- When enabled, only the minimum required content is sent, the destination
  is logged, and the operator assumes the data-transfer responsibility.

## Data retention

- Uploaded files and results are kept only as long as the job needs them.
- Default retention: inputs deleted 7 days after job completion, results
  kept until the operator deletes them. Both are configurable; `0` disables
  persistence of inputs entirely.

## Logging redaction

- Logs never contain raw OCR text or field values; they reference
  `job_id`, file name and event codes only.
- Debug/visualization dumps (P1) are opt-in and written inside the local
  data directory only.

## Access rules

- The service (P7) binds to localhost by default; remote exposure is an
  explicit deployment decision.
- If an optional database is configured (PostgreSQL), it lives on the same
  trusted network and holds the same retention rules.
- No telemetry of any kind is sent by the engine itself.
