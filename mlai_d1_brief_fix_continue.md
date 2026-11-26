# Brief mlai — D1 fix vòng 1 (tiếp): hoàn thành các mục còn dở

Branch: `d1-provenance` (LV3, HEAD `bc1d5df`, có thay đổi chưa commit).
Vòng fix trước dừng vì hết bước (146 calls), chưa commit, chưa viết "Done".
Đã xong theo tóm tắt của nó: F1 (truyền TransformLog vào recognize_image + _extract_coil_tables/_extract_fields), F2 (prov thật cho Cell/Table/FieldValue), F3 (cột TATR đủ, test expect 4 ô). Verify trên working tree đã pass (pytest+validate+ruff+mypy exit 0) — nhưng việc chưa xong, KHÔNG được coi là hoàn thành.

## Làm nốt các mục còn mở (theo đúng thứ tự)
1. **F4(c):** test end-to-end qua `IndustrialVision.process` assert `TextBlock.prov` non-empty, `coord_space="original"`.
2. **F5:** giới hạn `pages[0]` (chỉ trang 1) — sửa gọn được thì sửa, không thì ghi rõ giới hạn + lý do trong báo cáo, không giấu. Table/Cell prov phải set cả `page` và `scale`. Ghi chú giới hạn đã biết: `tokens_to_blocks` mất traceability khi token khác page/scale; `_map_bbox` chỉ map 2 góc.
3. **Eval gates:** chạy `benchmark.validation_eval` + `benchmark.industrial_eval`, báo cáo số thật. ĐÃ BIẾT: industrial_eval trên main `d42f24c` cũng `0.500/0.000/0.000` y hệt D1 — KHÔNG phải regression của D1, KHÔNG sửa code để chữa con số này; chỉ báo cáo cả 2 số + ghi rõ.
4. **Viết lại `D1_FIX_VERIFY_REPORT.md`** với số thật của vòng này (số test pytest thực tế, validate, ruff, mypy, validation_eval, industrial_eval cả 2 nhánh) + giải thích vì sao báo cáo cũ ghi 35/0.0.
5. **Dọn working tree trước khi commit:** `git checkout -- uv.lock` (nó bị ghi lại ngoài ý muốn) và `git checkout -- benchmark/results_industrial.json` (artifact của eval, không phải thay đổi code). Chỉ commit đúng file code + test + báo cáo.
6. **COMMIT** gọn trên branch `d1-provenance`. KHÔNG push, KHÔNG deploy, KHÔNG merge.

## Quy tắc kiểm chứng (bắt buộc)
- Chạy check KHÔNG pipe: ghi log ra file, đọc exit code từng lệnh. Chỉ tin exit code + output thật.
- Nếu môi trường chặn tạo file test mới: viết toàn bộ file test trong khối fenced ở `D1_FIX_VERIFY_REPORT.md`, liaison sẽ đặt file giúp. Không bỏ test.
- Kết thúc bằng "Done" + tóm tắt những gì đã sửa trong log.
