# Brief test-only: TẠO tests/test_validation.py cho P5 (người dùng yêu cầu rõ ràng)

NGƯỜI DÙNG (Henrry) YÊU CẦU RÕ RÀNG: tạo mới file `tests/test_validation.py` cho dự án Image Extraction Engine (P5 validation & confidence). Đây là yêu cầu trực tiếp của người dùng — được phép tạo file test mới. Ngoài file test này, KHÔNG tạo file mới nào khác, KHÔNG sửa code production (chỉ sửa code khi test phát hiện lỗi thật và ghi rõ trong report).

## Quy tắc đứng
- KHÔNG `rm -rf` dưới mọi hình thức. KHÔNG deploy, KHÔNG commit, KHÔNG push — liaison làm.
- Chỉ sửa file test + (nếu cần) sửa code production khi test chứng minh có lỗi; mọi sửa code phải ghi vào report.
- Vướng thì dừng + viết `BLOCKED.md`, KHÔNG đoán, KHÔNG bỏ qua.
- Chạy check KHÔNG pipe qua tail/head, ghi log ra file, đọc `$?`.
- Làm trên nhánh `p5-review` (đang checkout sẵn), KHÔNG đổi nhánh. Xong viết `P5_TEST_REPORT.md` rồi dừng.

## Bối cảnh
Vòng sửa P5 (fix review của LightVela AI) đã xong code nhưng `tests/test_validation.py` chưa được tạo — workspace từ chối tạo file test mới trong lượt đó. Vòng này CHỈ viết test, chứng minh các fix đã đúng. Code hiện tại (đã kiểm chứng): `_eval_formula` tính được `THICK * WIDTH * 2` = 12.0; rule ID đã de-dup (`COIL_NO_FIELD_UNIQUE` / `COIL_NO_TABLE_UNIQUE`); `validate_result` đã gọi `normalize_field`, `validate_fields` (dynamic schema), `resolve_ambiguity`; mypy engine + benchmark 0 lỗi; pytest 80 pass.

## Test cần viết (tối thiểu, đặt trong tests/test_validation.py)
(a) `_eval_formula` smoke test: công thức số học có biến (vd `THICK * WIDTH * 2`) trả đúng số; công thức sai cú pháp trả None.
(b) `load_rules` ID-collision test: hai YAML cùng ID phải warn (không ghi đè lặng lẽ) và cả hai rule đều chạy.
(c) End-to-end "chữ số bị hoán vị trong cột số PHẢI bị flag": một ExtractionResult có cell số bị hoán vị (vd `1234` → `1324`) đi qua `validate_result` phải sinh finding (không im lặng).
(d) Ambiguity qua `validate_result`: giá trị gây nhầm (vd `I0`) đi qua pipeline phải trả đề xuất + needs_review, KHÔNG tự áp dụng đề xuất.
(e) Calibration split: test khẳng định calibrator fit trên một nửa, đo ECE trên nửa còn lại (không fit + đo cùng tập).
(f) Wiring test: khẳng định `validate_result` thật sự gọi normalize + dynamic-schema + ambiguity (vd mock/spy hoặc kiểm finding `DYNAMIC_*` / `AMBIGUITY_*` xuất hiện trên input tương ứng).
(g) Thêm: test rule `NUMERIC_ANY_RANGE` (generic, không phụ thuộc tên cột) và test thousands-grouping `12,34` bị flag mơ hồ thay vì parse lặng thành 1234.

## Check cuối (ghi exit code vào P5_TEST_REPORT.md)
- `.venv/bin/python -m pytest tests/ -q` (phải pass toàn bộ, kể cả test mới)
- `.venv/bin/python -m ruff check engine benchmark tests`
- `.venv/bin/python -m mypy engine benchmark`
- Ghi vào report: số test mới, từng test chứng minh fix nào, pytest/ruff/mypy exit code, mục nào chưa test được + lý do.
