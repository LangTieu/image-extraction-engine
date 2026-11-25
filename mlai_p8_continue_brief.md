# Brief: P8 — Benchmark & Optimization (vòng tiếp nối)

Bạn là ML AI Code. Repo: `/root/image-extraction-engine`, branch `p8-review` (WIP commit `1700270`: benchmark/harness.py, benchmark/robustness.py, benchmark/run.py — vòng 1 dừng ở giới hạn 30 phút/lượt, đang chạy smoke run).

## Đầu tiên
- `git merge main` (main đã lên `530dcd5` — bản sửa CI mypy: pyproject overrides + ruled/pdf/screen; P8 chỉ thêm file benchmark nên không xung đột, nếu có thì giữ phần của bạn và báo rõ).
- Đọc lại `mlai_p8_brief.md` (bản gốc còn trong `~/workspace/aws-quick/` trên máy điều phối — nếu cần, hỏi liaison cấp lại; nội dung chính: harness + metrics + so sánh + robustness + performance + tuning + error analysis + CI gate + report).

## Tiếp tục từ chỗ vòng 1 dừng
- Vòng 1 đang lặp smoke run `.venv/bin/python -m benchmark.run --split dev --tag smoke` và sửa lỗi `PipelineVariant` trong run.py/harness.py. Hoàn thành smoke run trước, rồi làm tiếp theo thứ tự: metrics đầy đủ (CER/WER qua jiwer, table/field/coil accuracy, thời gian, router accuracy, error-catch/review rate, ECE + bootstrap CI) → comparison matrix (PaddleOCR vs Tesseract vs ensemble; TATR vs OpenCV+OCR vs hybrid vs Docling; preprocessing on/off) → robustness (nhiễu tăng dần, điểm gãy) → performance (p50/p95, RAM/CPU, cProfile) + optimization có số baseline → tuning per-category trên dev split → error analysis → CI gate job vào `.github/workflows/ci.yml` (subset chạy được trên ubuntu-latest, không cần tesseract binary hay TATR weights) → report `docs/reports/benchmark_report.md` + chart PNG.
- Thêm `jiwer` + `matplotlib` vào `pyproject.toml` (đã cài trong venv, vòng 1 chưa thêm) để env mới chạy được harness.
- Nhớ các giới hạn đã Chốt: seed 35 mẫu tổng hợp (không ảnh thật, không bịa GT); Qwen local KHÔNG tải (máy không đủ RAM/đĩa); Gemini Vision OFF; không tính năng product mới.

## Quy tắc đứng
- Không tạo file test mới trong vòng này (vòng test riêng sau). Không `rm -rf`, không xóa file. Không commit, không push, không deploy, không merge. Không ghi secret/key thật. Không download model weights lớn.
- Chạy check KHÔNG pipe, ghi log, đọc exit code. Chạy full suite (pytest + validate + ruff + mypy `engine benchmark service tests`) trước khi dừng.
- Vướng chỗ nào: ghi `BLOCKED.md` rồi DỪNG. Gần hết giới hạn 30 phút/lượt thì viết `P8_REPORT.md` (làm được gì, số liệu chính, còn lại gì) rồi DỪNG — đừng cố nhồi.
