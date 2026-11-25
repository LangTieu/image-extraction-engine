# Brief: fix OCR pipeline returning zero text on a real HMI photo (mlai)

Repo: `/root/image-extraction-engine`, branch `ocr-hmi-fix` fresh from main `5f6cb42`.
Do NOT push to main. Do NOT deploy. Commit on branch `ocr-hmi-fix` only; liaison merges + deploys.
30-minute per-run limit: if time runs out, commit WIP and list remaining items in the report.

## Problem (verified live by the liaison, 25/11 ~11:5x)
Henrry tested the engine with a REAL photo of a POSCO TCM PLC HMI screen (1672x941 JPEG, `/tmp/tcm-plc.jpg` on this machine, also `~/workspace/image-engine/tcm-plc.jpg` on the VM). Live job `job_999fcf0b1e77` completed in ~165 s but extracted NOTHING: `fields: []`, `text_blocks: []`, `tables: []`. Warnings: "screen boundary not detected; using full frame", "glare on screen: 4.0% of pixels blown out", "possible moiré interference (score 1.00)", "NO_PROFILE_MATCHED: falling back to generic industrial_hmi parsing".
Decisive control experiment (liaison, same machine, same file): plain `tesseract 5.3.4 --psm 11` reads **542 words** from the photo ("322 TCM SECTION", "DELIVERY ENTRY EXIT CENTER", ...). Sanity: it reads `/tmp/invoice-test.png` perfectly ("INVOICE 12345 Total 100.00"). So the engine's pipeline DISCARDS text that Tesseract itself sees — the bug is in our pipeline, not the image.

## Tasks
1. **Reproduce locally first.** Run the pipeline on `/tmp/tcm-plc.jpg` (benchmark harness or a direct script — pick the fastest path that exercises the REAL code path the API uses) and confirm 0 text blocks before the fix. Find WHERE the text is lost: preprocessing (glare/moiré handling destroying text?), screen-boundary detection (cropping to a wrong/empty region?), OCR routing (wrong engine/PSM for this input?), confidence filtering (blocks dropped below a threshold?), or result assembly (blocks computed but not returned?). Trace it with evidence — print/log intermediate counts at each stage.
2. **Fix it so a real HMI photo yields text.** Minimal, targeted change in the pipeline (engine/ + service/ as needed). Do not redesign the pipeline. Keep the industrial profile behaviour for the seed/placeholder cases (validate 35/35 must stay green, eval F1 0.800 must not regress).
3. **Processing time.** 165 s for one photo is slow (P8 smoke said ~3 s on placeholders). Report where the time goes; remove obvious waste (e.g. duplicate OCR passes) if it is safe, but non-zero extraction is the primary goal — do not sacrifice correctness for speed.
4. **Regression test (REQUIRED).** Add a test to an EXISTING test file (do NOT create a new test file — the guard denies it): use a REAL text-bearing image (render one with PIL or reuse a seed scene with known text — NOT the 1x1 placeholders) and assert the pipeline returns non-empty text blocks/fields for it. The test must FAIL on the pre-fix code (prove it) and PASS after.
5. **Live proof on this machine.** Start the API locally (uvicorn on a test port, fresh SQLite file), upload `/tmp/tcm-plc.jpg`, wait for completion, and record the result: text_blocks count + a sample of the extracted text + processing time. Do NOT touch the deployed container.

## Checks (NO pipes — log to file, read exit codes)
- `.venv/bin/python -m pytest -q -p no:warnings` (exit 0; 155 baseline + new test(s)).
- `.venv/bin/python -m ruff check .`, `.venv/bin/python -m mypy engine service benchmark`, `python -m benchmark.validate` 35/35.
- Do NOT run the full benchmark. Do NOT deploy.

## Report
Write `OCR_HMI_FIX_REPORT.md` in repo root: where the text was lost (stage + evidence), what was changed (per-file), the regression test + its pre-fix failure evidence, the live upload proof (text_blocks count, sample text, processing time), and any remaining gaps (e.g. field extraction still needs a matched profile). End with the commit hash on `ocr-hmi-fix`.
