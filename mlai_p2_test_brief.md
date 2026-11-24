# P2-test brief — add durable P2 tests (mlai, IB4)

## Task (one fix only, do not start P3)
Add the missing P2 pytest coverage. `P2_REPORT.md` notes no new test
files were added this phase (the harness denied creation). The user
(the liaison, on Henrry's behalf) explicitly asks for them now.

## Items
1. Add `tests/test_ocr.py`: backend interface + NFC normalization,
   tesseract backend (word TSV, `vie+eng`), reading order
   (columns/lines/`reading_order`), PDF text-layer fast path vs OCR
   path, multi-scale re-OCR retry, orchestrator fallback + `bbox_original`
   mapping through a homography. Use small synthetic fixtures (rendered
   text via PIL, tiny PDFs via pypdfium2) — do NOT download models in
   tests; PaddleOCR backend tests must skip gracefully when the model
   cache is absent (or use a stub engine implementing the same ABC).
2. Add `tests/test_router.py`: Smart Router feature scoring, keyword
   cues, `unknown` fallback when best score < 0.3, `register_rule`
   override.
3. Run `.venv/bin/python -m pytest tests/ -q` — all tests (old + new)
   must pass. Run `ruff check engine benchmark tests` and `mypy engine` —
   both clean.
4. Run `.venv/bin/python benchmark/validate.py` — must still pass.
5. Update `P2_REPORT.md`: new test count, what the tests cover. Then stop.

## Standing rules (do not break)
- Add-only to shared files; never rewrite a shared file from scratch.
- NEVER `rm -rf` anything. Never delete files except ones this fix creates.
- NEVER deploy, commit or push — the liaison does that.
- If you get stuck: STOP. Write the blocker and exactly what you need
  into `BLOCKED.md` in the project dir, then stop the run. Do NOT guess,
  do NOT work around it silently, do NOT skip ahead to P3. The liaison
  checks the log every 5 minutes and will supply what you need.
- If the harness denies creating a file again, STOP and write that exact
  denial into `BLOCKED.md` instead of working around it.
