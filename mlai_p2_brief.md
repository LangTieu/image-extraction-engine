# P2 brief — Image Extraction Engine (mlai, IB4)

## Task (one phase only)
Implement **Phase P2 — General OCR + Smart Image Router** of the Image
Extraction Engine, following the P2 prompt in `prompts_aws_quick.md` (in
`/data/home/image-extraction-engine/`). Read `plan.md`, `P0_REPORT.md`
and `P1_REPORT.md` first. Build on P0/P1 (schema, preprocessing) — do NOT
rewrite them. P2 scope only; do not start P3.

## Standing rules (do not break)
- Add-only to shared files; never rewrite a shared file from scratch.
- NEVER `rm -rf` anything. Never delete files except ones this phase creates.
- NEVER deploy, commit or push — the liaison does that.
- If you get stuck on anything: STOP. Write the blocker and exactly what
  you need into `BLOCKED.md` in the project dir, then stop the run. Do NOT
  guess, do NOT work around it silently, do NOT skip to the next phase.
  The liaison checks the log every 5 minutes and will supply what you need.
- If the P2 prompt needs a package that is not installed, STOP and write
  it into `BLOCKED.md` (do not install anything yourself — the install
  step is denied for you; the liaison runs it).
- P0/P1 documented proposals are the defaults — proceed with them; list
  every assumption in your report.

## Done means
- All P2 acceptance criteria from the P2 prompt are met.
- `pytest` passes (run it with `.venv/bin/python -m pytest tests/ -q`).
- `benchmark/validate.py` still passes (`.venv/bin/python benchmark/validate.py`).
- Write `P2_REPORT.md`: what was delivered, test results, assumptions,
  open items. Then stop.
