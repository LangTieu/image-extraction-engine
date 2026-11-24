# P1 brief — Image Extraction Engine (mlai, IB4)

## Task (one phase only)
Implement **Phase P1 — Preprocessing** of the Image Extraction Engine, following
the P1 prompt in `prompts_aws_quick.md` (in `/data/home/image-extraction-engine/`).
Read `plan.md` and `P0_REPORT.md` first. Build on P0's schema/spec — do NOT
rewrite them. P1 scope only; do not start P2.

## Standing rules (do not break)
- Add-only to shared files; never rewrite a shared file from scratch.
- NEVER `rm -rf` anything. Never delete files except ones this phase creates.
- NEVER deploy, commit or push — the liaison does that.
- If you get stuck on anything: STOP. Write the blocker and exactly what you
  need into `BLOCKED.md` in the project dir, then stop the run. Do NOT guess,
  do NOT work around it silently, do NOT skip to the next phase. The liaison
  checks the log every 5 minutes and will supply what you need.
- P0's documented proposals (input limits, language scope, etc.) are the
  defaults — proceed with them; list every assumption in your report.

## Done means
- All P1 acceptance criteria from the P1 prompt are met.
- `pytest` passes (run it with `.venv/bin/python -m pytest tests/ -q`).
- `benchmark/validate.py` still passes (`.venv/bin/python benchmark/validate.py`).
- Write `P1_REPORT.md`: what was delivered, test results, assumptions,
  open items. Then stop.
