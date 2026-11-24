# P5 fix round — 24/11 (báo cáo)

Thực hiện theo `mlai_p5_fix_brief.md`. Đã sửa:

1. **rules.py — sandbox formula**: thêm `ast.Load` và các toán tử so sánh
   (`Eq, NotEq, Lt, LtE, Gt, GtE`) vào `_ALLOWED_NODES`. Trước đây mọi formula
   có biến (ctx = Load) hoặc so sánh đều bị từ chối âm thầm (`_eval_formula`
   trả None) nên cross-field rules không bao giờ chạy.
2. **Trùng ID rule**: `load_rules` giờ `logging.warning` khi hai file YAML
   định nghĩa cùng một ID (kẻ sau thắng, giữ hành vi cũ); đổi tên rule bị trùng
   trong `default.yaml` (`COIL_NO_UNIQUE` → `COIL_NO_FIELD_UNIQUE` /
   `COIL_NO_TABLE_UNIQUE`) và ghi chú rõ cột theo seed.
3. **Nối normalize → dynamic schema → ambiguity vào `validate_result`**:
   - normalize: giá trị str được làm sạch/parse theo type của profile (ghi đè
     in-place), grouping mơ hồ → warning `NORMALIZE_AMBIGUOUS`;
   - dynamic schema: contract type/format/min-max từ profile chạy trên field
     dict, finding `DYNAMIC_*`;
   - ambiguity: chạy cho field và cả cell bảng theo format regex (YAML +
     `FieldDef.format_regex`); `proposed` → warning `AMBIGUITY_PROPOSED`,
     `ambiguous` → error `AMBIGUOUS_VALUE`; đề xuất ghi vào
     `proposals` trên FieldValue/Cell và `extensions["validation"]["ambiguity"]`.
     Không tự áp dụng đề xuất nào.
4. **Eval trung thực** (`benchmark/validation_eval.py`): ba loại lỗi
   (confusable / transposition / digit_drop), `profile_name="steel_coil_mill"`,
   layout thứ hai với tên bảng/cột/field khác seed, recall theo từng loại lỗi,
   confidence theo từng vị trí (field/cell), calibration fit/test tách nửa/nửa.
   Số thật (35 results, seed 42):
   - seed layout: precision 1.000, recall 0.667, F1 0.800; recall theo loại:
     confusable 1.000, transposition 0.417, digit_drop 0.750; ECE raw 0.214 →
     Platt held-out 0.083.
   - renamed layout: recall 0.000 (28/28 lỗi bị bỏ sót) → xác nhận phụ thuộc
     tên seed; đã thêm rule tổng quát không phụ thuộc tên
     `NUMERIC_ANY_RANGE` (type `numeric_range_any`) quét mọi cột số.
5. **Mypy**: `mypy engine/ benchmark/` = 0 lỗi (trước đó 37 lỗi, 5 file).
6. **Sửa nhỏ**: normalize không parse nhóm nghìn 2 chữ số nữa (flag mơ hồ);
   nhãn cell fallback dùng tên cột thay vì chỉ chỉ số; threshold review hỗ trợ
   key theo cột (`table.column`, `profile.table.column`); chỉ rule ERROR mới
   tính là `rule_ok=False` (warning-only không còn bị phạt 0.25 vô lý).
7. **Docs**: cập nhật `docs/reports/p5_validation.md` với số mới.

## Chưa xong (bị chặn)

- `tests/test_validation.py` — brief yêu cầu tạo mới nhưng workspace từ chối
  tạo file test mới (guard "Not done: Add a new test file"). Nội dung test
  (a)–(f) đã soạn sẵn; cần người dùng xác nhận để ghi file.

## Kiểm chứng

- `.venv/bin/python -m pytest tests/ -q` → 80 passed.
- `.venv/bin/python -m mypy engine/ benchmark/` → 0 lỗi.
- `.venv/bin/python -m benchmark.industrial_eval benchmark/seed` →
  routing=1.000 f1=0.933 unit_acc=0.875 (giữ nguyên baseline).
- `.venv/bin/python -m benchmark.validation_eval benchmark/seed` → số ở mục 4.
