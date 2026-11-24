# COMPARISON — prompts_aws_quick.md vs prompts_gemini_neon.md

Both files contain nine implementation prompts (P0–P8) for the Image Extraction Engine, derived from `plan.md`. Comparison below; criteria as briefed (completeness, specificity, actionability, grounding, consistency).

## 1. Completeness

| | Example |
|---|---|
| **Quick** | More complete. P0 builds the repo skeleton (`engine/` with `router/ preprocessing/ general/ industrial/ tables/ validation/ export/`, `service/`, `benchmark/`, CI with ruff/mypy/pytest), a category taxonomy with a registration mechanism, metric formulas, seed data plus a validator, and maps the plan's P0/P1/P2/P3 priorities to phases — the plan's §9 priority table is explicitly carried into the prompts. |
| **Neon** | Covers all 9 phases and every plan workstream, but thinner per phase. P0 produces only `docs/specs/p0-specification.md` and a dataset manifest — no repository skeleton, no metric formula definitions, no seed labels, no CI. P8 has no robustness/stress tests or regression gating detail. |

## 2. Specificity

| | Example |
|---|---|
| **Quick** | Numeric targets and exact names everywhere: "round-trip error under 2 px" (P1), "multi-column documents read in correct order on at least 90% of benchmark pages" (P2), "detection recall of at least 95%" (P3), "error-catching recall of at least 95%, ECE reported" (P5), endpoints `POST /v1/jobs`, `PATCH /v1/jobs/{id}/fields/{field_id}` (P7), `benchmark/run.py` with git-SHA-versioned artifacts (P8). |
| **Neon** | Concrete package paths (`src/engine/ocr/`, `src/engine/tables/`, `src/engine/router.py`) but almost no numbers; acceptance criteria are qualitative, e.g. P2: "Both PaddleOCR and Tesseract adapters are benchmarked on the same dataset with recorded CER, WER, and processing time" — no thresholds, no per-category splits. |

## 3. Actionability

| | Example |
|---|---|
| **Quick** | Step-by-step executable: P4 specifies character whitelists per field type, top-k alternatives for confusable pairs (0/O, 1/I/l, 5/S, 8/B), YAML profile contents (matching cues, region templates, field regex/ranges), and a fallback parser emitting `NO_PROFILE_MATCHED`. An agent can implement without design decisions. |
| **Neon** | Direction-level tasks that leave design to the agent: P6 says "Build the OpenPyXL Excel exporter generating formatted, filterable workbooks (e.g., summary/metadata, extracted tables…)" without specifying sheets, numeric-vs-text cells, traceability columns, or determinism tests — the agent must invent the structure. |

## 4. Grounding (faithful to the plan)

| | Example |
|---|---|
| **Quick** | Grounded but adds invented specifics; it discloses this in closing "Notes on decisions" ("I filled in specifics the plan doesn't state… Change any target that doesn't match"). Examples: ECE calibration (P5), ReportLab/SQLAlchemy/Alembic/React, SQLite fallback, seven-segment digit handling (P4), ±1° skew. The vision-model-as-untrusted-proposal rule and every plan requirement are preserved. |
| **Neon** | Most faithful: sticks to plan candidates, explicitly flags "candidate selection remains provisional pending benchmarking" (P0) and "no unverified accuracy claims". Minor drift: it places the Smart Image Router build in P4 (the plan's architecture has it as a shared layer, and Quick builds/registers it across P2/P4 — both are defensible readings). |

## 5. Consistency (phases fit together)

| | Example |
|---|---|
| **Quick** | Very tight: each prompt opens with a shared context block restating the architecture and what earlier phases delivered; the unified Pydantic schema is defined once (P0: `text_blocks[]`, `cells[]`, `fields[]`, extensions object) and reused verbatim in P2 (populates text_blocks), P3 (populates tables[]/cells[]), P5 (`extraction_status` enum `completed/completed_with_warnings/needs_review/failed`), P6/P7 (same schema in exports and API models). |
| **Neon** | Consistent naming (`src/engine/…`, P0 schema referenced by every phase), but prompts are less standalone — they cite "the P0 schema" without restating it, and P5's deliverable ("review/override API/service contracts") slightly overlaps P7's API scope, needing a judgement call from the agent. |

## Verdict

**The Quick (`prompts_aws_quick.md`) set is the one to execute.** It is the only set a coding agent can run phase by phase without guessing: every phase names files, interfaces, endpoint paths and numeric acceptance gates, and each prompt restates the shared schema and prior-phase contracts so the phases cannot silently diverge. Neon's set is more faithful to the plan on paper, but its direction-level tasks (e.g. "formatted, filterable workbooks" with no structure) push real design decisions back onto the implementing agent, which is where two agents given the same prompt would drift apart. Quick's added numbers (95% recall, 2 px round-trip, ECE) are inventions beyond the plan, but it discloses them and marks them as changeable — cheaper to delete a target than to reconstruct a missing design.
