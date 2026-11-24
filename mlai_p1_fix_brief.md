# P1-fix brief — CER regression (mlai, IB4)

## Task (one fix only, do not start P2)
Fix the P1 CER regression documented in `P1_REPORT.md` ("preprocessing
currently increases CER on every scene kind"). The brief's bar —
"preprocessing must not hurt OCR" — is not met yet.

## Items (from the P1 report's recommendation)
1. Tighten `detect_quadrilateral` to prefer the largest *inner* content
   quad over frame lines (on true perspective scenes it locks onto the
   canvas edge, not the panel).
2. Gate the `perspective` and `sharpen` steps on the quality report —
   only run them when quality flags a real defect (they false-fire on
   frontal/clean scenes and cost 1–3 points of CER).
3. Re-run `benchmark/preprocess_cer.py` and confirm preprocessed CER is
   no worse than raw CER on the synthetic scenes (orientation-only
   configuration already meets this bar — keep it as the fallback).
4. Run `ruff check engine benchmark tests`, `mypy engine`,
   `.venv/bin/python -m pytest tests/ -q`,
   `.venv/bin/python benchmark/validate.py`. All must pass.
5. Update `P1_REPORT.md`: new benchmark numbers, what changed, and
   whether the "must not hurt OCR" bar is now met. Then stop.

## Standing rules (do not break)
- Add-only to shared files; never rewrite a shared file from scratch.
- NEVER `rm -rf` anything. Never delete files except ones this fix creates.
- NEVER deploy, commit or push — the liaison does that.
- If you get stuck: STOP. Write the blocker and exactly what you need
  into `BLOCKED.md` in the project dir, then stop the run. Do NOT guess,
  do NOT work around it silently, do NOT skip ahead to P2. The liaison
  checks the log every 5 minutes and will supply what you need.
