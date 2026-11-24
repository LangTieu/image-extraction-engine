# Brief: P5 fix round — sửa theo review của LightVela AI (round-2, 24/11 17:14)

## Quy tắc đứng (đọc kỹ, vi phạm là dừng việc)
- Chỉ ADD vào file dùng chung, KHÔNG viết lại file từ đầu, KHÔNG `rm -rf` dưới mọi hình thức.
- KHÔNG deploy, KHÔNG commit, KHÔNG push — liaison làm. Xong việc thì dừng, viết `P5_FIX_REPORT.md` rồi dừng.
- Vướng chỗ nào thì dừng + viết `BLOCKED.md` (mô tả đúng chỗ vướng + cần gì), KHÔNG đoán, KHÔNG bỏ qua sang mục khác.
- Chạy mọi check KHÔNG pipe qua tail/head, ghi log ra file, đọc `$?` để kết luận (pipe làm mất exit code).
- Làm trên nhánh `p5-review` (đang checkout sẵn), KHÔNG đổi nhánh.

## Tạo file test — NGƯỜI DÙNG YÊU CẦU RÕ RÀNG
Người dùng (Henrry) yêu cầu rõ ràng trong brief này: TẠO MỚI file `tests/test_validation.py` và mọi file test khác cần cho vòng sửa này. Đây là yêu cầu trực tiếp của người dùng, được phép tạo file test.

## Bối cảnh
P5 (validation & confidence) đã code xong, pytest 80 pass, nhưng review độc lập của LightVela AI (đã clone repo, checkout p5-review commit 6040d01, chạy suite + eval + probe lỗi held-out) kết luận: recall 0.96 là giả (đo trên đúng loại lỗi mà rule đã viết sẵn cho seed), cross-field chưa từng chạy, 2 module chưa được nối, mypy 8 lỗi ở benchmark. Liaison đã kiểm chứng độc lập 5 điểm chính — TẤT CẢ ĐÚNG (xem mục kiểm chứng cuối brief). Nhiệm vụ vòng này: sửa hết, có test chứng minh từng lỗi đã sửa, báo cáo số thật.

## Việc cần làm

### 1. Cross-field chết — `engine/validation/rules.py:336-355` (ƯU TIÊN CAO NHẤT)
- `_ALLOWED_NODES` thiếu `ast.Load` (ast.walk sinh ra `Load` làm ctx của mọi `ast.Name`) nên `_eval_formula` trả `None` với mọi công thức. Liaison chạy live: `_eval_formula("THICK * WIDTH * 2", {"THICK": 2.0, "WIDTH": 3.0})` → `None`.
- Sửa: thêm `ast.Load` (và mọi node type còn thiếu mà công thức số học cần, kể cả toán tử so sánh nếu formula dùng) vào `_ALLOWED_NODES`.
- Test: unit test chứng minh một công thức cross-field biết-trước-không-khớp (vd weight ≠ thick×width×density) PHẢI fire ra issue.

### 2. Trùng rule ID — `engine/validation/rules/default.yaml:37` và `:93`
- Cả hai đều `id: COIL_NO_UNIQUE`. `load_rules` (rules.py:68-83) key theo ID nên định nghĩa sau (HOT_COIL_NO/COLD_COIL_NO) lặng lẽ thay thế định nghĩa trước (COIL_NO/COIL_ID) — cột của rule đầu không bao giờ được kiểm.
- Sửa: đổi ID một trong hai (giữ cả hai cột đều được kiểm), và `load_rules` PHẢI cảnh báo (warn/log) khi gặp ID trùng thay vì ghi đè lặng lẽ.
- Test: load_rules với ID trùng phải warn; cả hai rule đều chạy.

### 3. Module chết — nối vào pipeline hoặc gỡ khỏi báo cáo
- `resolve_ambiguity`, `normalize_field`, `validate_fields`/`dynamic_schema` KHÔNG có caller nào ngoài re-export ở `engine/validation/__init__.py`. Docstring `validate_result.py:1-5` và `docs/reports/p5_validation.md:4-15` mô tả chúng như đã nối — SAI.
- Sửa (ưu tiên nối, không gỡ): nối normalize → dynamic schema → ambiguity vào `validate_result` thật sự, để ambiguity ("đúng 1 ứng viên qua format rule thì đề xuất + needs_review=true, không bao giờ đoán") chạy được trên kết quả thật.
- Test end-to-end: một kết quả có ký tự gây nhầm (vd "I0") đi qua `validate_result` PHẢI trả về đề xuất mơ hồ + needs_review, không đoán.
- Nếu có phần nào không nối được vì lý do kỹ thuật thật: ghi rõ trong P5_FIX_REPORT.md và SỬA báo cáo `p5_validation.md` cho đúng thực tế (không được để báo cáo ghi sai).

### 4. Eval trung thực — `benchmark/validation_eval.py`
- Hiện tại `inject_error`/`degrade_result` chỉ tạo lỗi trên giá trị `str` (isinstance check ở dòng 63, 83), nên lỗi toàn rơi vào cột đã có rule viết sẵn cho seed; rule hard-code đúng tên bảng/cột của seed (`coil_list`, THICK, HOT_COIL_NO...), và `default.yaml:44-46` có comment thừa nhận seed-tuning.
- Sửa eval:
  a. Thêm loại lỗi held-out: hoán vị ký tự kề (transposition), rớt chữ số trong GIÁ TRỊ SỐ (numeric), không chỉ swap chữ trong str.
  b. Chạy eval với `profile_name="steel_coil_mill"` (hiện eval truyền None ở dòng 112 nên rule theo factory không bao giờ được đo).
  c. Thêm một layout/bảng thứ hai với tên bảng/cột KHÁC seed để rule không qua được nhờ khớp tên seed.
  d. Báo recall THEO TỪNG LOẠI LỖI + held-out, không chỉ một con số chung.
  e. Calibration: tách fit/test (hoặc ghi rõ Platt ECE là in-sample). Sửa nhãn calibration: confidence phải theo từng field, không dùng một scalar document_confidence cho mọi vị trí trong doc (dòng 143-146 hiện tại là nhãn tròn).
- Mục tiêu: recall held-out phải đo được thật, không còn là artifact. Ghi số thật vào report, kể cả khi số xấu.

### 5. Mypy — `benchmark/validation_eval.py` có 8 lỗi
- Liaison chạy live: đúng 8 lỗi (vd :142 `"ValidationIssue" has no attribute "col_index"`, :141 table_name/row_index, :82/:121/:132/:139 type tuple).
- Sửa hết 8 lỗi. Chạy mypy trên CẢ `engine/` VÀ `benchmark/` đều sạch (lần trước liaison chỉ chạy engine nên sót benchmark — từ giờ check cả hai).

### 6. File test — `tests/test_validation.py` (MỚI, người dùng yêu cầu rõ ràng ở trên)
- Tối thiểu phải có: (a) `_eval_formula` smoke test; (b) `load_rules` ID-collision test; (c) end-to-end "chữ số bị hoán vị trong cột số PHẢI bị flag"; (d) ambiguity qua `validate_result`; (e) calibration split held-out; (f) test khẳng định `validate_result` thật sự gọi normalize/dynamic-schema/ambiguity.

### 7. Các điểm nhỏ trong review (sửa hết)
- `normalize.py:88-92`: thousands-grouping chấp nhận nhóm 2 chữ số — `12,34` → 1234 lặng lẽ. Sửa: nhóm 2 chữ số phải flag, không parse lặng.
- `validate_result.py:202`: fallback cell flag ghi `f"{table}.{col_index}"` (số index) — sửa thành tên cột để reviewer đọc được.
- `validate_result.py:133`: ngưỡng needs_review key theo tên bảng — sửa để ngưỡng theo được từng field/cột.
- `validate_result.py:96`: field chỉ có warning bị `rule_ok=False` (trừ 0.25 confidence) mà không kèm needs_review reason — kiểm tra consumer, gắn reason khi warning làm giảm confidence.
- `rules.py` load_rules: warn khi ID trùng (đã nêu ở mục 2, nhắc lại để khỏi sót).

### 8. Báo cáo
- Cập nhật `docs/reports/p5_validation.md` cho đúng thực tế sau sửa (bỏ mọi câu sai: test file, recall, calibration).
- Viết `P5_FIX_REPORT.md`: từng mục trên — đã sửa gì (file:dòng), test nào chứng minh, số đo mới (recall theo loại lỗi + held-out, ECE fit/test tách riêng, pytest/mypy/ruff), mục nào chưa sửa được + lý do.

## Check cuối (chạy hết, ghi exit code vào report)
- `.venv/bin/python -m pytest tests/ -q` (ghi log ra file, đọc `$?`)
- `.venv/bin/python benchmark/validate.py`
- `.venv/bin/python -m ruff check engine/ benchmark/`
- `.venv/bin/python -m mypy engine/ benchmark/`
- `.venv/bin/python benchmark/validation_eval.py` (ghi số mới vào report)
- `.venv/bin/python benchmark/validate.py` + industrial eval (routing/F1 phải giữ 1.000/0.933)

## Kiểm chứng của liaison (để đối chiếu, không cần làm lại)
- `_eval_formula("THICK * WIDTH * 2", ...)` → None live (thiếu ast.Load).
- `COIL_NO_UNIQUE` xuất hiện 2 lần (default.yaml:37, :93).
- grep `resolve_ambiguity|normalize_field|dynamic_schema` ngoài `__init__.py`: 0 caller.
- mypy `benchmark/validation_eval.py`: đúng 8 lỗi.
- `degrade_result` chỉ inject lỗi khi `isinstance(value, str)`.
