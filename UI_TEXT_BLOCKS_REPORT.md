# Report: show extracted `text_blocks` in the UI + timestamp/badge fix

Branch `ui-text-blocks` (fresh from main `0a1ded0`). API v7.0.0.

## What changed, per file

### `service/web/src/api.ts`
- New `TextBlock` type (`key`, `text`, `bbox`, `readingOrder`, `confidence`, `language`) and
  `normalizeTextBlock()` — maps the engine's `text_blocks` entries (`text`, `bbox` as
  `x0,y0,x1,y1` pixels via the existing `normalizeBBox`, `reading_order`, `confidence`,
  `language`) and assigns a stable UI key (`{fileId}/b{index}`).
- `ResultFile` gained `textBlocks: TextBlock[]`; `normalizeResultFile` reads
  `result.text_blocks` (top-level `text_blocks` as fallback). The review-merge fallback
  file gets an empty list.
- `normalizeJob` now routes `created_at`/`updated_at` through `normalizeTimestamp()`,
  which appends `Z` to timezone-less ISO strings.

### `service/web/src/util.ts`
- New shared `parseUtcDate()` used by both `formatDateTime()` and `timeAgo()`: an ISO
  string without a timezone designator is treated as UTC (append `Z`) instead of being
  parsed as the viewer's local time.

### `service/web/src/views/ReviewView.tsx`
- Text blocks are drawn on the image as dashed overlay boxes (new `block` tone), under
  the reviewable field boxes.
- Clicking a box, or an entry in the new "Extracted text" list (ordered by
  `reading_order`, showing text, `#order`, confidence % and language), selects the
  block. Keyboard/prev-next navigation stays field-only.
- The "Selected item" panel (`Inspector`) shows the block: crop of its bbox, extracted
  text, confidence badge/bar and language — read-only, no review actions.
- When a file has no reviewable fields but has text blocks, the first block is
  auto-selected (both on load and when switching file tabs).

### `service/web/src/views/ResultsView.tsx`
- Each file card now lists its extracted text blocks in reading order (text + confidence
  % + language). The "No fields were extracted" message only shows when fields, tables
  and text blocks are all empty.

### `service/web/src/components/Inspector.tsx`
- Optional `block` prop with a read-only block view (crop, text, confidence, language).

### `service/web/src/components/ImageViewer.tsx`
- `OverlayBox.tone` extended with `'block'`.

### `service/web/src/styles.css`
- `.box-block` (dashed accent outline, solid when selected) and `.text-blocks`
  / `.text-block` list styles.

### `service/web/src/App.tsx` (badge fix)
- Jobs polling is no longer paused while a review screen is open; it runs at a slower
  cadence (30 s instead of 5 s) so the "n in progress" nav badge reflects live job
  statuses without stealing request budget from review actions.

## Regression tests + pre-fix failure evidence

Added to `tests/test_api.py` (UI ↔ API contract section):

- `test_ui_renders_text_blocks` — asserts `api.ts` normalizes `text_blocks` into
  `ResultFile.textBlocks` and that both `ReviewView.tsx` and `ResultsView.tsx` render
  `textBlocks`.
- `test_ui_timestamps_parse_naive_as_utc` — asserts `util.ts` has a shared
  `parseUtcDate()` used by both `formatDateTime` and `timeAgo`, and that it anchors
  timezone-less strings to UTC.

Pre-fix evidence (tests present, `service/web` reverted with `git stash`):

```
pytest exit=1
E   AssertionError: api.ts must normalize the API's text_blocks array
E   AssertionError: util.ts must define a shared UTC-aware timestamp parser
FAILED tests/test_api.py::test_ui_renders_text_blocks
FAILED tests/test_api.py::test_ui_timestamps_parse_naive_as_utc
```

After the fix the whole suite passes (157 tests, including these two).

## Live proof

- Started the API with a scratch SQLite DB, uploaded the real HMI photo
  `/tmp/tcm-plc.jpg`, job `job_f74670e45a73` reached `completed`, and
  `GET /v1/jobs/{id}/result` returned **13 text_blocks** (sample: `"V244h"` @0.91,
  `"| [ 322 [TCM SECTION-3 A PL | TCM | MENU | EXE"` @0.74).
- The same response confirms the timestamp bug mechanism: `created_at` came back as a
  naive ISO string `2026-11-25T06:30:59.276708` — no `Z`, no offset — which the browser
  previously parsed as local time (a UTC+7 viewer saw "7 h ago"). The UI now anchors
  such strings to UTC.
- `npm run typecheck` and `npm run build` pass; the built bundle
  (`dist/assets/index-*.js`) contains the overlay component (`text_blocks`,
  "Extracted text") and contains no `/api/v1` prefix.

## Remaining gaps

- The backend (SQLite store) still emits timezone-less timestamps; the UI is now
  tolerant, but a backend-side fix (return `...Z` / aware datetimes) would make the
  contract unambiguous for other clients.
- The absolute-time display now shows the correct instant in the viewer's locale;
  previously it happened to look "right" because both the parse error and the display
  were local.
