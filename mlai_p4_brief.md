# P4 brief — Industrial Vision (mlai, LV3)

## Context
Working dir on THIS machine: `/root/image-extraction-engine`
(git clone of LangTieu/image-extraction-engine, branch main — run `git pull`
first to confirm it is current). P0–P3 are done and verified
(schema, preprocessing, OCR + router, tables incl. TATR).
This run builds P4 only. Do NOT start P5.

## Task (from the Quick P4 prompt)
Build the separate Industrial Vision module for PLC/HMI control screens,
industrial dashboards, Hot Coil / Cold Coil tables, production lists,
product codes and coil IDs, thickness/width/weight/length, machine
parameters, alarms, operating states and process diagrams. Column
alignment and units are critical.

1. **Module isolation.** Create `engine/industrial/` as its own module
   behind the shared router interface. It must NOT modify General Vision
   code. It may only reuse shared components through public interfaces.
2. **Screen normalization.** Detect monitor bezels / screen boundaries,
   rectify perspective, normalize aspect ratio. Detect moiré and glare
   and turn them into warnings. Build on P1.
3. **Region detection.** Segment the HMI into panels, tables, label/value
   boxes, alarm banners and status indicators, using contours and color
   segmentation (typical HMI palettes, alarm red/yellow). Add an optional
   detector-model hook (interface only, no model download).
4. **Compact OCR.** Configure OCR for short alphanumeric strings and
   digits: character whitelists per field type, upscaled region crops,
   seven-segment / LCD-style digit handling if present. Record top-k
   alternatives for confusable characters (0/O, 1/I/l, 5/S, 8/B) —
   never guess, flag them.
5. **Coil table parsing.** Use the P3 table module, then map headers to
   canonical fields (ZONE, HOT_COIL_NO, COLD_COIL_NO, THICK, WIDTH,
   WEIGHT, LENGTH, product code) using profile aliases, including
   Vietnamese and abbreviated header variants. Keep row/column
   associations exact.
6. **Value–unit extraction.** Parse numbers (decimal and thousands
   separators), split out units (mm, m, kg, t, °C, bar, rpm, %, ...),
   link each value to its label or column. Keep raw text, parsed value
   and unit together.
7. **Alarms and states.** Extract alarm messages, codes, timestamps,
   severity (by color or keyword) and operating states
   (RUN, STOP, AUTO, MANUAL, FAULT, ...).
8. **Profile system (`profiles/*.yaml`).** Each factory/machine profile
   defines: matching cues (title text, layout anchors, colors), region
   templates (relative coordinates), field definitions (name, aliases,
   type, unit, regex format such as a coil ID pattern, plausible range),
   table schemas. Load profiles at runtime — a new factory is added
   without code changes. Ship at least TWO sample profiles.
9. **Generic fallback parser.** When no profile matches, extract all
   label–value–unit pairs and tables generically, set
   `document_type: industrial_hmi` with a NO_PROFILE_MATCHED warning.
10. **Router integration.** Register industrial categories
    (industrial_hmi, coil_table, machine_label, alarm_screen,
    process_diagram) and their routing cues — add-only to the router.
11. **Vision-model assist (interface only).** An interface to query
    Qwen2.5-VL (local) or Gemini Vision (opt-in, external) for layout
    interpretation of hard screens. Its output is a proposal only and
    must match OCR text or source pixels before it is accepted. It must
    never invent values. Do NOT download any vision model in this run;
    implement the interface + an unavailable stub.
12. **Evaluation.** `benchmark/industrial_eval.py`: Coil ID exact-match
    accuracy, field-level accuracy, unit-association accuracy and
    latency, on angled-photo HMI and coil-table benchmark sets
    (reuse the seed benchmark sets). Write results to
    `docs/reports/p4_industrial.md`.
13. **Checks.** Run `.venv/bin/python -m pytest tests/ -q` (all pass),
    `.venv/bin/python benchmark/validate.py` (35 passed),
    `ruff check engine benchmark tests` and `mypy engine` (both clean).
    Do NOT create files under `tests/` in this run — a separate test
    brief will add the P4 tests. Then write `P4_REPORT.md` and stop.

## Standing rules (do not break)
- Add-only to shared files; never rewrite a shared file from scratch.
- NEVER `rm -rf` anything. NEVER delete files.
- NEVER deploy, commit or push — the liaison does that.
- NEVER install packages (apt/pip/uv) — the liaison installs what you need.
  If a package is missing, STOP and write it into `BLOCKED.md`.
- If you get stuck: STOP. Write the blocker and exactly what you need
  into `BLOCKED.md` in the project dir, then stop the run. Do NOT guess,
  do NOT work around it silently, do NOT skip ahead to P5. The liaison
  checks the log every 5 minutes and will supply what you need.
