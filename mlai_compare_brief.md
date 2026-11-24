# Brief for ML AI Code — Compare two prompt sets, choose one, implement P0

## Context

You are building the **Image Extraction Engine** (Modular Hybrid Vision Engine)
from the plan in `plan.md`. Two different AI assistants each wrote a full set of
9 implementation prompts (one per roadmap phase P0–P8) from that same plan:

- `prompts_aws_quick.md` — written by AWS Quick (SMART mode).
- `prompts_gemini_neon.md` — written by Gemini Neon.

Both files are in this directory. Both are complete (9 phases each, same required
structure per prompt: objective, scope and boundaries, key tasks and steps,
technology candidates, acceptance criteria, expected deliverable).

## Task 1 — Compare and choose

Read both prompt files completely, then compare them on:

1. Completeness — does every phase cover everything the plan requires?
2. Specificity — concrete file paths, module names, function/class names,
   commands, numeric targets (not vague advice).
3. Actionability — can a coding agent execute the prompt step by step without
   guessing?
4. Grounding — does it stay faithful to the plan (no invented features,
   no dropped requirements)?
5. Consistency — do the phases fit together (shared schema, module names,
   file layout agreed across P0–P8)?

Write your comparison to `COMPARISON.md` in this directory: a short table
per criterion (Quick vs Neon, with one concrete example each), then a verdict:
**which prompt set fits you best and why** (2–4 sentences, specific, not generic).

## Task 2 — Implement P0 of the CHOSEN set

Implement ONLY phase P0 (Requirements & Data Specification) from the prompt
set you chose, in this directory (`/data/home/image-extraction-engine`).
Follow the chosen P0 prompt exactly: repository skeleton, spec documents,
unified Pydantic/JSON output schema, benchmark dataset skeleton with seed
labels and validator, metric definitions with stubs, privacy section.
Do NOT start P1–P8. Do NOT change anything outside this project directory.

## Rules

- NEVER run `rm -rf` or delete files outside this directory.
- After writing code, run the tests / validation yourself and report the exact
  exit codes and outputs. Every claim of success must come with the exact
  command output that proves it. Never invent a URL, ID, path, or output value.
- If a step fails, report it as failed with the error text. Do not report a
  failed step as success.
- When P0 is done, stop and write a short report at the end of `COMPARISON.md`
  (or a new file `P0_REPORT.md`): what you created/changed (file list),
  test/validation results with exit codes, and anything left open.
- Work in this directory only. Do not commit, push, or deploy anything.
