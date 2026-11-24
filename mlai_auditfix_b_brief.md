# Audit-fix brief B — industrial pipeline (mlai, LV3)

## Context
Working dir on THIS machine: `/root/image-extraction-engine`.
Second batch of the verified LightVela AI audit fixes. Brief A (eval,
mapping, TATR, BBox, tables_eval) is DONE and pushed (commit 8bcceb5).
This brief fixes the industrial-pipeline items. Do NOT redo brief A work.
Do NOT start P5. Do NOT touch the PDF charbox code (audit claim REFUTED).

## Items (in this order)
1. `engine/industrial/pipeline.py` — `_read_grid` header misalignment
   (real location is `industrial/pipeline.py:205`, NOT
   `preprocessing/pipeline.py` as the audit cited): `headers = [h for h
   in rows[0] if h]` drops empty header cells, while `_extract_coil_tables`
   uses `headers` positionally (`types`, `resolved`, `zip(resolved,
   raw_row)`) — one empty header shifts every later column. Fix by
   keeping positional alignment (empty header cells stay as placeholders
   so column indices line up), and guard `field_types[col_index]` against
   `IndexError` when fewer headers than columns.
2. `engine/industrial/values.py` — numeric parsing:
   - `_strip_thousands`: `"1,234"` currently becomes `"1.234"` (1000x too
     small, `ok=True`, no note). A thousands separator must be REMOVED
     (`"1234"`), not turned into a decimal point. Only treat `,` as a
     decimal separator when the pattern is unambiguous (e.g. a single
     comma with 1–2 digits after it and no thousands grouping); when
     ambiguous, keep the value but add a note and set `ok=False`
     (flag, never guess).
   - Compound units: `_UNIT_PATTERN` allows exactly one letter-run unit,
     so `"10 kg/m2"` / `"5 m/min"` fail entirely (`value=None`). Accept
     compound units with `/` (and `^2`/`^3`-style suffixes); if a unit
     cannot be parsed, return `value=None` WITH a note (already the
     case — keep it).
   - `format_regex`: `coil_table.py` already calls `disambiguate(...,
     field_def.format_regex)`; `schema/industrial_fields.py:119–123`
     (`validate_value`) enforces it but has NO production caller. Wire
     `validate_value` into the extraction path where a value is accepted
     (a value failing its `format_regex` must be flagged, not silently
     accepted). If wiring it in is not straightforward, say so in
     `AUDIT_FIX_REPORT.md` and leave it for P5 — do NOT fake it.
3. `engine/industrial/pipeline.py:262–267` + `values.py:102–111` —
   label/value pairing:
   - Pairing is pure substring matching on the whole region text
     (`spec.name.lower() in reading.text.lower()`). Change to
     token/word-boundary matching so a label only matches as a whole
     word (or whole token) in the text.
   - Single-letter aliases are real (`steel_coil_mill.yaml`: `"w"` for
     width, `"t"` for thickness) — `"t"` is a substring of nearly any
     text. Single-character aliases must match as standalone tokens
     only, never as substrings.
   - Silent default unit: `unit = m.group("unit") or default_unit or
     ""` stamps `default_unit` with no note. When the default is used,
     add a note (e.g. `"unit defaulted to <unit>"`) so it is visible.
     Never silently default a unit.
   - Related: `parse_value_unit` receives the whole region text
     including the label, and `_UNIT_PATTERN` anchors on a leading
     number, so label-prefixed text (e.g. `"WIDTH 1250"`) fails and
     returns `value=None`. Strip the matched label (and separators)
     from the text before parsing the number/unit.
4. `engine/industrial/pipeline.py:99–103` — `needs_review` never
   escalates: top-level status is `COMPLETED_WITH_WARNINGS if warnings
   else COMPLETED`, while field-level `needs_review` (`:292`) never feeds
   it, even though `ExtractionStatus.NEEDS_REVIEW` exists. Make any
   field/row with `needs_review` escalate the top-level status to
   `NEEDS_REVIEW`.
5. `engine/industrial/regions.py` + `alarms.py`:
   - The palette defines `"red2": [170,179]` (hue wraparound) but
     `_ALARM_COLORS = {"red", "yellow"}` omits `"red2"`, so red alarms
     at hues 170–179 never match the alarm-banner test. Include the
     wraparound range.
   - `parse_alarm_row` returns `None` when both timestamp and code
     regexes miss, and `_extract_alarms` silently skips `None`. Record
     a warning (unreadable alarm row) instead of dropping it silently.
6. `engine/industrial/screen.py:49–58` — dark-background HMI: the P4
   fix made dark quads fall back to the full frame with no perspective
   correction. Implement inversion-aware quad detection so a dark screen
   (bright text on dark background) is rectified like a bright one:
   detect the quad on the inverted image when the interior is dark.
   Verify on the seed `industrial_hmi` scenes (routing must stay 5/5).
7. `engine/tables/borderless.py:68` — region score is
   `min(1.0, len(tokens) / 12.0)`: any region with ≥12 tokens scores
   1.0 regardless of table-ness. Make the score reflect table structure
   (e.g. evidence of rows/columns/alignment), not just token count.
   Keep the borderless eval at 1.00 after the change.
8. `engine/tables/hybrid.py:92–99` — dedupe by exact float bbox
   equality (`cell.bbox not in keeper_bboxes`). Use an IoU/tolerance
   based dedupe instead (cells overlapping above a threshold count as
   duplicates).
9. `engine/ocr/multiscale.py:51–53` — on a retry hit the original token
   is replaced wholesale by the highest-confidence word in the padded
   retry crop, which may be a neighbour. Only substitute when the retry
   token clearly corresponds to the original (overlapping bbox / same
   position); otherwise keep the original text and flag the token.
10. `engine/ocr/router.py` — keyword matching is substring
    (`extract_keywords` returns `[kw ... if kw in lowered]`, flat `+0.4`
    per hit); below-threshold handling reports `confidence=min(1.0,
    best)` — the REJECTED best category's score, not confidence in
    "unknown" — and `scores` can exceed 1.0 before the cap. Match
    keywords on word boundaries; report below-threshold confidence as
    confidence in the "unknown" routing; cap category scores at 1.0
    BEFORE adding the keyword bonus (or fold the bonus inside the cap).
11. `engine/industrial/profiles.py:95–98, 133–148` — `aliases=tuple(
    spec.get("aliases", ()))` with no type check: a bare-string
    `aliases: "coil"` in YAML explodes into `('c','o','i','l')` (same
    for `header_aliases`). Coerce a bare string to a 1-tuple. Also
    `match_profile` accepts any `best_score > 0.0` (one title cue
    suffices): require at least 2 cues or a minimum score threshold —
    record the rule you chose in `AUDIT_FIX_REPORT.md`.
12. `engine/industrial/compact_ocr.py:182–218` (seven-segment) — NOTE
    ONLY, do not expand scope: no caller passes `seven_segment=True`
    today and the bundled profile sets `seven_segment: false`, so the
    single-largest-contour limitation cannot trigger. Add a code comment
    documenting that multi-digit seven-segment reads need caller-side
    slicing (already noted in code) and that the flag feeds
    `needs_review` via `reading.flags`. No behaviour change.

## Finish
- Re-run the industrial eval + tables eval and record before/after
  numbers in `AUDIT_FIX_REPORT.md` (append a "Brief B" section; do not
  overwrite the brief-A section). Routing must stay 1.000 and field F1
  must not regress below 0.933.
- Rerun all four checks and record results in `AUDIT_FIX_REPORT.md`:
  `.venv/bin/python -m pytest tests/ -q`,
  `.venv/bin/python benchmark/validate.py`,
  `ruff check engine benchmark tests`, `mypy engine` — all must pass.
  Then stop. Do NOT create files under `tests/` in this run.

## Standing rules (do not break)
- Add-only to shared files; never rewrite a shared file from scratch.
- NEVER `rm -rf` anything. NEVER delete files.
- NEVER deploy, commit or push — the liaison does that.
- NEVER install packages (apt/pip/uv) — the liaison installs what you need.
  If a package is missing, STOP and write it into `BLOCKED.md`.
- If you get stuck: STOP. Write the blocker and exactly what you need
  into `BLOCKED.md` in the project dir, then stop the run. Do NOT guess,
  do NOT work around it silently, do NOT skip ahead.
