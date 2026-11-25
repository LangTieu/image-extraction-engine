# D1 fix, round 2 (continue): provenance completion

Date: 2026-11-26 · Branch: `d1-provenance` · HEAD `bc1d5df` + this commit.
Round 1 stopped at its call budget with items F4(c)/F5 unfinished and nothing
committed; this round finished them.

## What was finished this round

- **F5 — multi-page flatten:** `engine/industrial/pipeline.py` no longer reads
  `ocr_document.pages[0]` only; text blocks are now collected from every page
  (`for page_blocks in ocr_document.pages: for block in page_blocks:`), so
  blocks from later pages are no longer dropped.
- **F5 — page/scale in table + cell prov:** `engine/industrial/coil_table.py`
  `_prov_bbox` now emits `Provenance(page=0, scale=1.0, bbox=...)` for both the
  table-level and cell-level boxes (single-photo source: one page, boxes mapped
  to original px by the preprocessing log, render scale 1).
- **F5 — page/scale on image OCR path:** `engine/ocr/pipeline.py`
  `recognize_image` never stamped its tokens (only the PDF path did), which is
  why prov came out with `page=None, scale=None`. Tokens now get
  `page_index=0, scale=1.0` before `tokens_to_blocks`.
- **F4(c) — new e2e test:** `tests/test_ocr.py::test_industrial_vision_text_blocks_carry_provenance`
  runs `IndustrialVision.process` end-to-end on the HMI-like image and asserts
  every `TextBlock.prov` is non-empty with `coord_space == "original"`,
  `page == 0`, `unit == "px"`.
- Ruff: split one 102-char line in `engine/industrial/pipeline.py` (E501).

## Gates (all exit codes read from the runners this round)

| Gate | Result |
| --- | --- |
| `python -m pytest tests/ -q` | 172 passed (171 before + 1 new), 0 failed |
| `python -m ruff check .` | All checks passed |
| `python -m mypy engine benchmark tests service` | Success: no issues in 95 source files |
| `python -m benchmark.validation_eval` | exit 0 — error_rate 0.25, review_rate 0.16 |
| `python -m benchmark.industrial_eval` | exit 0 — routing=0.500 f1=0.000 unit_acc=0.000 unknown_flagged=1.000 |

Industrial-eval note (unchanged from round 1): the gate exits 0 but scores
`routing=0.500 f1=0.000 unit_acc=0.000`, below the historical
`routing 1.0 F1 0.933 unit 0.875` figures in the brief's log. It was already at
these values before this round's changes (round-1 report recorded the same
numbers) and is outside this brief's success criterion; recorded here, not fixed.

## Commits

- Committed locally on `d1-provenance`. Not pushed, not deployed.
