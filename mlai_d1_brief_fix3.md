# mlai D1 fix round 3 — merge conditions from LightVela review round 2

Branch: `d1-provenance` (current HEAD `c08da96`). Work in `/root/image-extraction-engine` on LV3.
You fix the D1 Provenance/bbox phase so it can merge. Review round 2 verdict was
MERGE WITH MINOR FIXES (conditional). Full review record (read it first):
`review_d1_round2.md` in the repo root — conditions 1–5 below come from it.

## Established evidence — do NOT re-litigate
The liaison ran the decisive A/B industrial_eval on 26/11 in a healthy LV3 environment:
- `c08da96` (round 2): routing 0.5, field F1 0.0, unit 0.0
- `bc1d5df` (round 1): routing 0.5, field F1 0.0, unit 0.0
- The two result JSONs are byte-identical except runtime (40.37s vs 39.34s).
- All 5 coil samples: `NO_PROFILE_MATCHED`, routed to `industrial_hmi`, 0 fields.
  All 5 industrial_hmi samples route correctly, hence routing 0.5.
- CONCLUSION (proven): round 2 did NOT cause the collapse. The committed JSON at
  bc1d5df (routing 1.0 / F1 0.9333 / tp 35) was STALE. The collapse also exists on
  main `d42f24c` (liaison ran it 25/11: same 0.5/0.0/0.0). Do not spend time proving
  round 2 innocent again. Your job is to diagnose the collapse itself (condition 1).

## Condition 1 — diagnose the coil routing collapse + add an eval gate (HIGHEST)
1. Diagnose WHY every coil seed sample gets NO_PROFILE_MATCHED in the current
   environment. Investigate, in order: (a) what the coil profile matcher requires
   (cues/thresholds in the profile-matching code) vs what the rendered seed images
   actually contain (run OCR on a rendered coil seed image and read the text);
   (b) `git log` on the profile matcher, the coil table pipeline, and
   `benchmark/industrial_eval.py` — find the last commit where routing passed and
   what changed since; (c) whether the seed rendering or the preprocessing gates
   (image-correction merge `1ae048b`) changed what the matcher sees.
2. Fix the root cause so coil samples route to `coil_table` again and fields are
   extracted. If the root cause is a real code regression, fix the code. If the
   committed 1.0/0.933 was never reproducible in this environment, say so with the
   exact evidence (which commit, which run, which numbers) and fix whatever is
   actually broken now.
3. Add a gate to `benchmark/industrial_eval.py`: it must exit NON-ZERO when the run
   is degenerate — routing_accuracy 0.5 with field F1 0.0, or any sample with a
   ground-truth profile getting NO_PROFILE_MATCHED. A silent exit 0 on those scores
   is a bug (this is how the stale 1.0/0.933 survived unnoticed). Keep the gate
   narrow: it must not fail a legitimately low-but-real score; fail on the
   degenerate patterns above.
4. Re-run `benchmark/industrial_eval.py` fresh after the fix and commit the
   regenerated `benchmark/results_industrial.json`. The numbers in the committed
   JSON must match a real run you did in this round.

## Condition 2 — N2: FieldValue provenance page/scale
`engine/industrial/pipeline.py` `_prov_for_bbox` (~lines 645-660) builds
`Provenance(bbox=...)` without page/scale, so `FieldValue.prov` has
page=None/scale=None while TextBlock and Table/Cell use page=0/scale=1.0.
Stamp page=0, scale=1.0 there (single-image path), or document exactly why fields
are exempt. Keep it consistent with the other producers.

## Condition 3 — N3: one bbox coordinate-space convention, documented
`engine/tables/pipeline.py` (~107-133) remaps table/cell bbox into ORIGINAL coords
when a transform log exists, while industrial producers keep bbox in WORKING coords
with the original in `prov`. Pick ONE convention for what `bbox` means on every
model, apply it everywhere, and document it in `engine/schema/models.py`
(docstring on the bbox/prov fields). Consumers (validation bbox checks, export
preview overlays) must be able to tell which space a bbox is in. Do not leave two
contradictory conventions in the tree.

## Condition 4 — N4 + N7 + N8
- N4: `_map_bbox` (`engine/ocr/pipeline.py:27`, `engine/tables/pipeline.py:63`)
  maps only TL/BR corners; map ALL FOUR corners and take the true AABB. Update
  `test_bbox_original_after_known_deskew` — it currently blesses the 2-corner
  approximation as "expected"; fix the test to expect the correct 4-corner AABB.
- N7: `tests/test_ocr.py::test_industrial_vision_text_blocks_carry_provenance`
  must assert a NUMERIC original-space bbox (not just coord_space/page/unit meta):
  a known transform (e.g. scale x2) applied to a known box must produce the
  expected original-space numbers in `prov`.
- N8: restore a mixed-DPI per-page scale test: two PDF pages rendered at different
  DPI must produce different `prov.scale` values. (Coverage for this was dropped
  to 150-DPI-only in round 2.)

## Condition 5 — N5 + F6
- N5: give alarms (`AlarmEntry`, `engine/industrial/pipeline.py:508-521`) provenance,
  or write an explicit documented gap (where, why, what is missing) in the code and
  in the phase report. Silence is not an option.
- F6: rewrite `D1_FIX_VERIFY_REPORT.md` from scratch with numbers YOU verified in
  this round (real pytest count, real eval scores). No number may be copied from an
  older report or a stale committed JSON. If a claim cannot be verified, write that
  it is unverified — never present it as fact.
- Also fix N9 if it is a one-liner: `_ocr_text_shallow`
  (`engine/industrial/pipeline.py:272-276`) calls `recognize_image` without
  transform_log — pass the log through or add a comment explaining why the call
  cannot mislabel. (N6 reading_order collisions in flattened multi-page lists:
  fix if trivial, else note as a known limitation in the report.)

## Check rules (mandatory — a wrong check voids the round)
- Run every check WITHOUT pipes (`| tail`, `| grep` forbidden in gates): run the
  command, write output to a log file, then read the file and the exit code.
  Example: `.venv/bin/python -m pytest tests/ -q > /root/d1f3_pytest.log 2>&1; echo EXIT=$?`
- Gates, all must exit 0: pytest (full suite, count the passes and report the exact
  number), `benchmark/validate.py`, `ruff check engine benchmark tests`,
  `mypy engine benchmark`, `benchmark/industrial_eval.py` (fresh run, with the new
  gate active), validation eval.
- If your environment blocks creating a NEW test file, do NOT skip the test: write
  the complete test file in a fenced code block inside `D1_FIX_VERIFY_REPORT.md`
  and state clearly that the liaison must place it. (Same rule as rounds 1–2.)
- Do NOT rewrite `uv.lock`. Do NOT touch anything outside D1 scope (no API, no UI,
  no deploy config). Do NOT print or commit any secret/key.
- Commit everything on branch `d1-provenance` with a clear message
  (`D1 round 3: <what>`). End with "Done" plus the verified numbers (pytest count,
  industrial_eval routing/F1/unit, validate result) in your final message and in
  `D1_FIX_VERIFY_REPORT.md`.
