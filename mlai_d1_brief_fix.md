# Brief mlai — D1 fix vòng 1: sửa 6 findings review LightVela (DO NOT MERGE)

Branch: `d1-provenance` (đang checkout trên LV3, HEAD `bc1d5df`). Base main `d42f24c`.
KHÔNG push, KHÔNG deploy, KHÔNG merge. Chỉ sửa code + test trên branch này, commit gọn.
KHÔNG sửa `uv.lock` (nếu nó bị ghi lại thì `git checkout -- uv.lock`).
Review đầy đủ: `review_d1_round1.md` trong repo (đọc kỹ trước khi sửa).
Diff review: https://github.com/LangTieu/image-extraction-engine/compare/d42f24c...d1-provenance

## Sửa theo thứ tự (bắt buộc đủ 5 mục)

### 1. F1 (CRITICAL) — truyền transform_log vào OCR production
- `engine/industrial/pipeline.py:134`: `self._ocr.recognize_image(working)` → `recognize_image(working, transform_log=report.transform)` (`report.transform` đã có trong scope, đang dùng ở ~:218).
- Kiểm chứng: `engine/ocr/pipeline.py` chỉ map về tọa độ gốc khi có `transform_log`; không có thì `bbox_original` luôn None và prov fallback về tọa độ đã xử lý.
- Thêm test: sau một phép deskew đã biết (ví dụ xoay −5°), assert `block.bbox_original != block.bbox` và `bbox_original` khớp tọa độ gốc thật.

### 2. F2 (CRITICAL) — Table/Cell/FieldValue prov trong production
- Thực trạng: `engine/industrial/pipeline.py:257-301` (`_extract_coil_tables`) không dùng `TablePipeline`; `_read_grid` + `rows_to_table` (`engine/industrial/coil_table.py`) không set prov, không nhận `TransformLog`. Kết quả thật: `Table.prov == []`, `Cell.prov == []`, `FieldValue.prov == []`.
- Ưu tiên: nối prov vào `_read_grid` / `rows_to_table` + FieldValue với cùng `transform_log` như F1.
- Nếu nối thật sự không làm được trong vòng này: CẮT khẳng định Cell/Table/FieldValue khỏi phạm vi D1 một cách trung thực (sửa docstring/schema claim + ghi rõ trong báo cáo cái gì chưa có prov), KHÔNG để code test-only giả vờ như production đã có. Không được bịa.
- `FieldValue.bbox` hiện ở tọa độ đã xử lý, không nhãn không gian — xử lý cùng mục này.

### 3. F3 (HIGH) — cột cuối TATR bị mất
- `engine/tables/tatr.py:155-160`: rows phát theo band (`range(len(rows))`, lấy cả hàng cuối) nhưng cols vẫn `range(len(cols) - 1)`, `n_cols = len(cols) - 1`.
- Sửa: phát cột theo band `range(len(cols))`, `n_cols = len(cols)`.
- Sửa test `test_tatr_cell_offset_covers_every_cell_including_last_row` (`tests/test_tables.py`): dựng 2 cột thì expect đủ 2 cột (ô (0,0),(0,1),(1,0),(1,1)), không assert `n_cols == 1` nữa.

### 4. F4 (MEDIUM-HIGH) — thay test lặp bằng test wiring thật
- (a) Bỏ/sửa assert `cell.prov[0].bbox == cell.bbox` trong `tests/test_tables.py` (đúng theo cấu tạo, không bao giờ fail được) — thay bằng assert kiểm được wiring thật (prov khác bbox đã xử lý khi có transform, hoặc prov khớp tọa độ gốc đã biết).
- (b) Bỏ/sửa test `test_pdf_pages_carry_page_index_and_scale_into_prov` (`tests/test_ocr.py`) tự dựng đối tượng Provenance — thay bằng test end-to-end qua producer thật (`GeneralOCR.recognize_pdf` / `IndustrialVision.process`) assert page/scale/prov được điền bởi code chạy thật.
- (c) Thêm assert producer điền prov (không chỉ schema chấp nhận): ít nhất một test end-to-end qua `IndustrialVision.process` assert `TextBlock.prov` non-empty với `coord_space="original"` sau khi sửa F1.

### 5. F5 (MEDIUM) — ngữ nghĩa PDF nhiều trang + DPI (làm phần trong phạm vi D1)
- `industrial/pipeline.py:154` chỉ lấy `ocr_document.pages[0]` — ghi rõ trong báo cáo: đây là giới hạn đã biết (chỉ trang 1) hay sửa để giữ đủ trang. Nếu sửa được gọn trong vòng này thì sửa; nếu không, ghi rõ giới hạn + lý do, không giấu.
- Table/Cell prov (khi nối ở F2) phải set cả `page` và `scale`, không để 2 trang/DPI khác nhau chung một nhãn tọa độ.
- Ghi chú trong báo cáo: `tokens_to_blocks` mất traceability khi token trong 1 dòng khác page/scale (`page=None`), và `_map_bbox` chỉ map 2 góc nên bbox có thể bị cắt dưới homography thật — ghi là giới hạn đã biết nếu chưa sửa.

## Eval công nghiệp — KHÔNG phải regression của D1, đừng đuổi theo nó
- Liaison đã chạy đối chứng: D1 branch `routing=0.500 f1=0.000 unit_acc=0.000` VÀ main `d42f24c` (worktree LV3 `/tmp/iee-main`) cũng `routing=0.500 f1=0.000 unit_acc=0.000` — y hệt nhau. Lần verify đầu của D1 eval vẫn `routing 1.0 F1 0.933 unit 0.875`, mà commit sau đó (`bc1d5df`) chỉ đổi 3 dòng bọc code E501 — không thể làm tụt F1. Kết luận: eval công nghiệp hiện không ổn định / phụ thuộc môi trường trên LV3, KHÔNG phải lỗi D1.
- Trong vòng này: chạy lại `benchmark.industrial_eval` trên branch sau khi sửa, báo cáo số liệu + số đối chứng main như trên, ghi rõ không phải regression. KHÔNG sửa code để "chữa" con số eval này.
- Viết lại `D1_FIX_VERIFY_REPORT.md` với số THẬT từ lần chạy của vòng này: số test pytest thực tế (vòng trước agent chạy được 170 passed — báo cáo cũ ghi 35 là SAI, do chạy trong môi trường lỗi), validate, ruff, mypy, validation_eval, industrial_eval (cả 2 nhánh). Giải thích ngắn gọn vì sao lần chạy cũ ra 35/0.0.

## Quy tắc kiểm chứng (bắt buộc)
- Chạy check KHÔNG pipe: ghi log ra file, đọc exit code từng lệnh (`pytest`, `benchmark.validate`, `ruff check .`, `mypy engine benchmark tests service`, `benchmark.validation_eval`, `benchmark.industrial_eval`). Không tin kết luận "check failed/passed" của harness, chỉ tin exit code + output thật.
- Nếu môi trường chặn tạo file test mới: viết toàn bộ file test trong khối fenced ở `D1_FIX_VERIFY_REPORT.md`, liaison sẽ đặt file giúp. Không bỏ test.
- Commit gọn trên branch `d1-provenance`, viết báo cáo cập nhật vào `D1_FIX_VERIFY_REPORT.md`. KHÔNG push, KHÔNG deploy, KHÔNG merge.
