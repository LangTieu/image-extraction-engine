# Brief for ML AI Code — Compare two prompt sets and choose one (SMALL TASK)

## Context

Two AI assistants each wrote a full set of 9 implementation prompts
(one per roadmap phase P0–P8) for the Image Extraction Engine, from the same
plan (`plan.md`):

- `prompts_aws_quick.md` — written by AWS Quick (SMART mode).
- `prompts_gemini_neon.md` — written by Gemini Neon.

Both files are in this directory.

## Task — compare and choose ONLY (do not write any code)

Read both prompt files completely, then compare them on:

1. Completeness — does every phase cover everything the plan requires?
2. Specificity — concrete file paths, module names, numeric targets.
3. Actionability — can a coding agent execute it step by step without guessing?
4. Grounding — faithful to the plan (no invented features, no dropped requirements)?
5. Consistency — do the phases fit together (shared schema, module names)?

Write the result to `COMPARISON.md` in this directory: a short table per
criterion (Quick vs Neon, one concrete example each), then a verdict:
**which prompt set fits you best and why** (2–4 sentences, specific).

Do NOT write any implementation code. Do NOT create any other files.
When COMPARISON.md is written, stop and report the verdict in one paragraph.
