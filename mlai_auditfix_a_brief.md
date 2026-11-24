# Audit-fix brief A — measurement & geometry (mlai, LV3)

## Context
Working dir on THIS machine: `/root/image-extraction-engine`.
An independent audit of this repo (LightVela AI) was verified line-by-line
against the real code by the liaison. Most claims CONFIRMED. This brief
fixes the measurement & geometry batch. A second brief (industrial items)
follows after this one. Do NOT start P5. Do NOT touch the PDF charbox
code — that audit claim was REFUTED (get_charbox returns
left,bottom,right,top and the unpacking is correct).

## Order of work (do in this order)
1. Fix `benchmark/industrial_eval.py` FIRST: `_gt_fields` assumes row 0
   is the header and iterates `table.rows[1:]`, but the unified schema
   stores headers in `Table.columns` and data-only rows in `Table.rows`
   (`grid_to_table` consumes `body[0]` into `columns`, `rows = body[1:]`).
   So the eval silently drops the first data row of every GT table.
   Fix it to use `Table.columns` as headers and ALL of `Table.rows` as
   data. Then re-run `benchmark/industrial_eval.py` and record the TRUE
   numbers (routing / F1 / unit_acc) in `AUDIT_FIX_REPORT.md` — they may
   differ from the 1.000 / 0.933 reported before; report the real ones.
2. Fix the coordinate-mapping chain (`engine/preprocessing/`):
   - `mapping.py:58`: `add()` does `matrix @ self._cumulative`, but the
     post→pre convention requires `H_old @ H_new`. Fix the order and
     fix the docstring formula (it states the wrong formula).
   - `transforms.py:419–420, 429–430`: `trim_borders`/`crop_region`
     build the post→pre matrix `[[1,0,left],[0,1,top]]` and then pass
     it to `_inverse_affine()`, which inverts it AGAIN. Fix so
     `crop_region((10,20,30,40))` maps post point `(0,0)` to `(10,20)`
     (verify with a throwaway script under /tmp, not a test file).
     `rotate`/`upscale`/`correct_perspective` use `_inverse_affine`
     correctly — do not touch them.
   - `transforms.py:414, 416`: `trim_borders` bottom/right are wrong:
     `bottom = argmax(rows[::-1]) + 1 + margin` is the trailing-empty
     count, not the last content row; correct is
     `height - argmax(rows[::-1]) + margin` (same for `right`).
   - After the fix, re-run `benchmark/validate.py` and the preprocessing
     round-trip check; `round_trip_error` must stay small AND the
     forward map must now be correct (check `map_to_original` against
     a hand-computed case, e.g. crop offset (10,20) then 2x upscale:
     post (4,4) must map to (12,22)).
3. Fix `engine/tables/tatr.py` (`_structure()`):
   - Cells are built in crop coordinates but `tokens` are full-image;
     `grid_to_table` → `assign_tokens` compares bboxes directly with
     no offset. Offset cell bboxes by `region.bbox` before matching.
   - Last row dropped: cells are built for `range(len(rows) - 1)` —
     emit the last detected row band too.
   - `_mark_span` crash: `max()` on an empty generator raises
     `ValueError` when a spanning-cell box starts above all detected
     rows — guard it (flag the cell instead of crashing).
   - Re-run the TATR eval and record before/after numbers.
4. Fix `engine/schema/models.py:33–36`: the BBox `@field_validator`
   just `return v` — actually validate `x1 > x0` and `y1 > y0`.
5. Fix `benchmark/tables_eval.py`: the loop takes the first extracted
   table with `region_iou > 0.5` and `break`s with no exclusion, so one
   extracted table can "match" several GT tables. Use best-IoU match
   with exclusion (one extracted table matches at most one GT table).
6. Rerun all four checks and record results in `AUDIT_FIX_REPORT.md`:
   `.venv/bin/python -m pytest tests/ -q`,
   `.venv/bin/python benchmark/validate.py`,
   `ruff check engine benchmark tests`, `mypy engine` — all must pass.
   Write `AUDIT_FIX_REPORT.md` (per item: what changed, before/after
   numbers, checks) then stop. Do NOT create files under `tests/` in
   this run.

## Standing rules (do not break)
- Add-only to shared files; never rewrite a shared file from scratch.
- NEVER `rm -rf` anything. NEVER delete files.
- NEVER deploy, commit or push — the liaison does that.
- NEVER install packages (apt/pip/uv) — the liaison installs what you need.
  If a package is missing, STOP and write it into `BLOCKED.md`.
- If you get stuck: STOP. Write the blocker and exactly what you need
  into `BLOCKED.md` in the project dir, then stop the run. Do NOT guess,
  do NOT work around it silently, do NOT skip ahead.
