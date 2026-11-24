# Brief P6: Export Engine (chỉ 1 phase — P6, không làm phase khác)

Làm đúng 1 phase P6 theo prompt AWS Quick (file prompts_aws_quick.md, mục "P6: Export Engine"). Repo hiện ở main commit 500b38b (P5 đã merge). P5 đã có: validated ExtractionResult (confidence, needs_review, warnings, audit trail), mọi giá trị trace được về bbox/cell nguồn. JSON Schema thống nhất ở docs/spec/schema_v0.json.

## Quy tắc đứng (vi phạm là dừng)
- Chỉ ADD code mới / sửa file khi cần cho P6. KHÔNG viết lại file dùng chung từ đầu (add-only).
- KHÔNG `rm -rf` dưới mọi hình thức. KHÔNG deploy, KHÔNG commit, KHÔNG push — liaison làm.
- KHÔNG tạo file test mới trong lượt này (vòng test riêng sẽ làm sau, giống P2/P3/P5).
- Vướng thì dừng + viết `BLOCKED.md` ghi rõ cần gì, KHÔNG đoán, KHÔNG bỏ qua.
- Chạy check KHÔNG pipe qua tail/head, ghi log ra file, đọc `$?`.
- Xong viết `P6_REPORT.md` rồi dừng.

## Việc cần làm — engine/export/
1. `engine/export/base.py`: interface `Exporter.export(result, options) -> ExportArtifact` (path, MIME type, checksum) + registry để format mới chỉ cần đăng ký exporter mới, không sửa core.
2. XLSX (openpyxl — đã cài 3.1.5): 1 sheet/bảng + sheet Summary (document type, status, warnings) + sheet Traceability (cell ref → source page, bbox, confidence, review status, correction history ID). Frozen header row, auto-filter, column widths, số phải là số (không lưu số dạng text) với number format, unit ở header hoặc cột unit riêng. Tô màu low-confidence / needs-review + cell comment ghi lý do.
3. CSV: 1 file/bảng, UTF-8 (tùy chọn BOM cho Excel tiếng Việt), delimiter + decimal separator cấu hình được. Sidecar `*_meta.csv` (confidence + traceability) tùy chọn.
4. JSON: full unified schema payload, validate against docs/spec/schema_v0.json trước khi ghi; tùy chọn "values only" vs "full with provenance".
5. Image previews (JPEG/PNG, OpenCV/Pillow — đã có): overlay lưới bảng, bbox field, tô màu confidence xanh/vàng/đỏ + legend. Tùy chọn crop thumbnail từng field.
6. PDF report (reportlab 5.1.0 — vừa cài): cover (job metadata), từng trang preview có chú thích, bảng đã trích, tóm tắt warnings/review, tổng quan rule validation.
7. Batch exports: XLSX gộp (1 sheet/nguồn hoặc bảng gộp + cột source_file) + ZIP bundle kèm manifest.
8. Traceability + manifest: mọi giá trị export đều trace được về vị trí nguồn + confidence; viết manifest JSON liệt kê artifacts, checksums, engine/module versions, profile dùng.
9. Determinism: cùng input cho JSON/CSV byte-stable (timestamp loại ra sau flag). Sample outputs từ benchmark samples vào docs/samples/exports/.
10. Dọn tồn đọng nhỏ (làm đầu tiên, 1 chỗ): sửa lỗi mypy pre-existing duy nhất ở tests/test_tables.py:156 ("Cannot override writeable attribute with read-only property") — file này từ vòng P3, không được đổi hành vi test, chỉ sửa cho mypy tests/ sạch.

## Check cuối (ghi exit code vào P6_REPORT.md)
- `.venv/bin/python -m pytest tests/ -q` (102 test hiện tại phải pass hết)
- `.venv/bin/python benchmark/validate.py` (35/35)
- `.venv/bin/python -m ruff check engine benchmark tests`
- `.venv/bin/python -m mypy engine benchmark tests` (phải 0 lỗi sau khi sửa test_tables.py:156)
- Chạy thử export 1 kết quả mẫu từ benchmark/seed ra cả 5 format + đọc lại XLSX/CSV đối chiếu giá trị (round-trip tay, ghi kết quả vào report: số bảng, số dòng, có drift không).
- Ghi vào report: file nào tạo/sửa, từng format đã chạy thử ra sao, mypy/ruff/pytest exit code, mục nào chưa làm được + lý do.
