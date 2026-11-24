# P7 TEST REPORT

## Status: FIXED — full suite green (vòng test tiếp tục, theo `mlai_p7_test_continue_brief.md`)

Nhánh: `p7-tests`. Liaison đã đặt `tests/test_api.py` (19 test). Vòng trước: 13 pass / 6 fail. Vòng này sửa 3 bug thật + 1 bug exports phát sinh, suite chạy hết xanh.

## Checks đã chạy (vòng này)
- `.venv/bin/python -m pytest tests/ -q` — exit 0, toàn bộ pass (không còn fail nào).
- `.venv/bin/python -m ruff check engine/export engine/tables/ruled.py engine/industrial/values.py service/api service/worker benchmark/tools tests` — "All checks passed!"
- `.venv/bin/python -m mypy engine benchmark tests` — "Success: no issues found in 82 source files".
- Probe thủ công: `RuledGridBackend().detect(img, tokens=[])` trên ảnh có 3 đường ngang + 3 đường dọc → 1 bảng 2x2; `parse_value_unit`: `"-3,5" -> -3.5`, `"-1,234.56" -> -1234.56`, `"+2,5" -> 2.5`, `"1,234.56 kN" -> 1234.56 kN`.

## Bug đã sửa
1. **API review/PATCH không nhận field của pipeline thật** (`service/api/app.py`): GET `/review` và PATCH `/v1/jobs/{id}/fields/{field_id}` chỉ tra `field.get("field_id") or field.get("field_name")`, trong khi worker dump `FieldValue.model_dump()` với key `name` → `/review` trả `field_id: None`, PATCH thật ra 404. Fix: thêm fallback `or field.get("name")` ở cả 2 chỗ.
2. **PATCH `correct` bỏ qua kết quả `validate_value`** (`service/api/app.py`): return list problems bị bỏ qua, giá trị sai format vẫn `validation: "ok"`. Fix: gọi `validate_value(field_id, value)` (key đã resolve sau fix 1), list khác rỗng → `validation = "failed: <problems>"`.
3. **`parse_value_unit` mất dấu âm** (`engine/industrial/values.py`): regex bắt group `sign` nhưng không áp vào value. Fix: sau khi parse `float(canonical)`, nếu `sign == "-"` thì `value = -value` (đã probe: `-3,5 -> -3.5`).
4. **Exports fail trên `result_json` một phần** (`service/worker/runner.py`, phát sinh khi chạy suite — đúng như brief dự đoán "nếu là bug exports riêng thì sửa luôn"): `ExtractionResult.model_validate(result_json)` chết vì thiếu `document_type`/`extraction_status` bắt buộc trong kết quả thật lẫn kết quả seed của test. Fix: `setdefault("document_type", "unknown")` + `setdefault("extraction_status", "completed")` trước khi validate.

## Lưu ý mypy trên file test
2 lỗi mypy trong `tests/test_api.py` (fixture dùng `yield` mà annotation `-> TestClient`): sửa **chỉ phần annotation** thành `Generator[TestClient, None, None]` (thêm import `typing.Generator`), không đổi assertion nào.

## Bug 0 (cv2 5.x) — đã fix trong code, không reproduce được env 5.x
`engine/tables/ruled.py` dùng index `ln[0][1]`/`ln[0][3]` (đúng cho output `(N, 1, 4)` của cv2 4.x) sẽ sai trên cv2 >= 5.0 trả `(N, 4)`. Fix: `np.asarray(raw).reshape(-1, 4)` rồi index `ln[1]/ln[3]` (ngang) và `ln[0]/ln[2]` (dọc) — chạy đúng với cả 2 shape. Env hiện tại là cv2 4.10 (2 test ruled đã pass cả trước và sau fix, không tái hiện được fail của liaison); probe thủ công xác nhận detect ra grid 2x2 đúng.

## Chưa làm
- Item 2 (coverage slice `engine/preprocessing/io.py` + `mapping.py` + case `values.py` thành test) — ngoài phạm vi brief vòng này (brief chỉ yêu cầu sửa 3 bug + chạy lại suite).
- Item 3 (Playwright e2e) — hoãn theo brief.
- Commit — chưa commit gì trên `p7-tests`, chờ chỉ định.
