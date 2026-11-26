Shared rules (repeated in every prompt)

- Implement ONLY this phase. Add no extra scope, refactor nothing outside the files named, and don't start the next phase.
- Don't push, open a release, tag or deploy. Commit locally on a branch named `d1-provenance`. A liaison reviews, merges and deploys.
- LV3 limits apply to everything you run or add: **2 CPU, 7 GB RAM, about 11 GB free disk, no paid APIs**. Don't add any model that downloads itself at runtime. Keep the Python/FastAPI/React stack, `.github/workflows/ci.yml` and `.github/workflows/deploy.yml` unchanged.
- Never change the semantics of the industrial expertise: YAML profiles (`engine/industrial/profiles/*.yaml`), coil IDs, alarms, seven-segment handling, skew/warp/brightness/moiré correction, and validation/confidence/review queue (`engine/validation/`).
- Pass/fail is decided by **exit codes only**. Don't pipe output through `tail` or `head`, and don't grep printed summaries to decide pass/fail.

Standard verification block (each prompt says which steps apply):

```bash
set -u
pytest; echo "pytest exit=$?"                                   # must be 0; pass count >= 165 + new tests
pytest --collect-only -q -o addopts="" > /tmp/collect.txt; echo "collect exit=$?"   # record total collected count in the report
python -m benchmark.validate benchmark/seed; echo "validate exit=$?"   # must be 0 (35 passed, 0 failed)
ruff check .; echo "ruff exit=$?"                               # must be 0
mypy engine benchmark service tests; echo "mypy exit=$?"        # must be 0
npm --prefix service/web ci && npm --prefix service/web run build; echo "web exit=$?"   # only where the prompt says so; must be 0
```

`benchmark/validate.py:main()` returns 1 if any ground-truth file fails. With the 7 seed categories × 5 samples, exit 0 means 35/35. Live smoke checks use `curl --fail --silent --show-error` against `$LIVE_BASE_URL` with header `X-API-Key: $IMAGE_ENGINE_API_KEY` (from `service/api/app.py:auth_and_rate_limit`). A non-zero curl exit is a failure. Live checks only read status or run a smoke upload. Never redeploy to run them.



D1: Provenance and bbox units

Context. You are working on the Image Extraction Engine (repo LangTieu/image-extraction-engine, commit d42f24c). It's a Python 3.11 / FastAPI / React modular vision engine with preprocessing (`engine/preprocessing/`), OCR (`engine/ocr/`), tables (`engine/tables/`), Industrial Vision (`engine/industrial/`), validation (`engine/validation/`) and export (`engine/export/`). All of it writes one Pydantic schema, `engine/schema/models.py:ExtractionResult`. It runs on an LV3 machine (2 CPU, 7 GB RAM, about 11 GB free disk, no paid APIs). 165 tests pass. This is the first of eleven phases that borrow small patterns from Docling (here: per-item provenance, `prov` with page + bbox, from `docling/datamodel/document.py` and `docling/datamodel/base_models.py`). Docling isn't a runtime dependency for this phase.

Objective. Give every text, table and cell node one source position: page + bbox in original-image coordinates, with an explicit unit. Fix the root coordinate bugs before more input types are added. `TransformLog` must state the unit and transform of each step.

Scope and boundaries.

In scope: a `Provenance`/`BBox`-unit model in the schema, populating it from OCR, TATR and the other table backends, and recording the unit in `TransformLog`.
Out of scope: new input formats (D2+), options objects (D3), changes to OCR or table algorithms, changes to the web UI.

Key tasks and steps.

Verified paths at d42f24c:
- `engine/tables/tatr.py`, `TATRBackend._structure()` lines 142–157: the `CellBox(...)` list adds the `region.bbox` offset to the crop-space TATR row and column bands. Confirm that offset is right for every cell, including the last row (line 155 comment) and the `cols[c][1]` right edge. Check `TATRBackend._mark_span()` (line 163+): spanning boxes are in crop coordinates but are compared against crop-space `rows`/`cols`. Keep that comparison in crop space, and make sure any bbox it writes is offset to full-image space.
- **Path correction:** the plan says "`mapping.py` region 58". The real file is `engine/preprocessing/mapping.py`. Line 57 is `TransformEntry(name=name, matrix=matrix, params=dict(params))  # type: ignore[arg-type]` inside `TransformLog.add()` (lines 48–59). Type `params` properly (`dict[str, float | int | str | bool]`) so the ignore goes, and add a `unit: Literal["px"] = "px"` field plus a `space_from`/`space_to` label ("processed" → "original") to `TransformEntry`.
- Schema, `engine/schema/models.py`: `BBox` (line 25) has no unit and `TextBlock`, `Cell`, `Table` and `FieldValue` have no page. Add `class Provenance(BaseModel)` with `page: int | None` (0-based, matching `SourceInfo.page` and `engine/ocr/pdf.py:PageText.page_index`), `bbox: BBox`, `coord_space: Literal["original"] = "original"`, `unit: Literal["px"] = "px"`, and `scale: float | None` (render DPI / 72 for PDF pages). Add an optional `prov: list[Provenance] = []` to `TextBlock`, `Cell`, `Table` and `FieldValue`. Keep the existing `bbox` fields, so the JSON stays backward compatible.
- `engine/ocr/pipeline.py:_with_original_coords()` (lines 124–132) sets `bbox_original` through three `# type: ignore[attr-defined]` lines. Declare `bbox_original` on the token/block dataclasses in `engine/ocr/base.py` (`OCRToken`, line 24) and `engine/ocr/pipeline.py`, so those ignores aren't needed. Then feed them into `prov`.
- `engine/tables/pipeline.py:_map_bbox()` (line 63) and `TablePipeline.extract()` (line 83): fill `Cell.prov`/`Table.prov` from the mapped original-space bbox.
- `engine/ocr/pdf.py:PdfiumTextLayer.read()` (lines 39–83) scales char boxes by `dpi / 72.0`. Record that scale in `Provenance.scale` so multi-scale pages stay traceable.
- Regenerate `docs/spec/schema_v0.json` with `engine/schema/models.py:export_json_schema()` only if `tests/test_schema.py` compares against it. Otherwise leave it alone.

Tests. Add at least 4 invariant tests, in a new file `tests/test_provenance.py`:
1. A TATR cell bbox after the region offset equals the crop bbox + `region.bbox[0:2]`. Mock `_struct`/`_struct_processor`, with no weights.
2. `TransformEntry.unit == "px"` and `map_to_original` round-trips within 2 px after rotate + upscale.
3. Two PDF pages rendered at different DPI (for example 150 and 300) give `Provenance.scale` values of 150/72 and 300/72, and the boxes land inside each page's pixel size.
4. `ExtractionResult.model_validate_json(result.model_dump_json())` keeps every `prov` entry identical.

Acceptance criteria.

At least 4 new tests pass. `pytest` exits 0 with at least 169 passing (165 baseline + 4).
`python -m benchmark.validate benchmark/seed` exits 0 (35/35), and `ruff check .` and `mypy engine benchmark service tests` both exit 0. The `type: ignore` count in `engine/` doesn't go up.
Live smoke: `curl --fail -sS "$LIVE_BASE_URL/v1/health"` exits 0. Upload one HMI image and one scrolling-table image with `curl --fail -sS -H "X-API-Key: $IMAGE_ENGINE_API_KEY" -F files=@hmi.png -F files=@table.png "$LIVE_BASE_URL/v1/jobs"`. Poll `GET /v1/jobs/{id}` until done, then download `GET /v1/jobs/{id}/result` to `result.json`. Run `python -c` with a script that loads `result.json` and runs `sys.exit(0 if all(0 <= b.x0 < b.x1 <= W and 0 <= b.y0 < b.y1 <= H for every prov bbox) else 1)`. It must exit 0. Deploying isn't required to pass this phase. Run it against a locally started `uvicorn service.api.app:app` if the live server doesn't have the branch yet.
Web build: not required. The UI isn't touched.

NOTE — test-file guard: if your environment blocks creating a new test file, do NOT skip the tests. Write the complete test file content in a fenced code block inside D1_REPORT.md and the liaison will place it at tests/test_provenance.py.

Expected deliverable. The schema `Provenance`, provenance wired through OCR and tables, `TransformLog` units, `tests/test_provenance.py`, and a short `D1_REPORT.md` with the exit codes, the test counts and the TATR offset finding. Don't push or deploy. The liaison merges.

