# Brief: Image Engine P8 — vòng tiếp nối 2 (fix ruff + hoàn thiện benchmark + báo cáo)

Bạn làm việc trên LV3 (hermes-wb), repo `/root/image-extraction-engine`, branch **`p8-review`**.
Main đã merge xong (HEAD `2086dab` "Merge branch 'main' into p8-review") — **KHÔNG merge main nữa.**

## Tình trạng vòng trước (đọc log trước khi làm)

Vòng tiếp nối 1 (log `mlai-p8-continue.log` trong repo) đã làm được:
- Merge main vào p8-review.
- Thêm `jiwer` + `matplotlib` vào `pyproject.toml` (2 lib đã cài sẵn trong `.venv`).
- Thêm CI gate job vào `.github/workflows/ci.yml`.
- Chạy smoke run `timeout 1500 .venv/bin/python -m benchmark.run --split dev --tag smoke` (chờ kết quả).

Vòng 1 DỪNG ở đây (hết lượt): `ruff check benchmark` báo **15 lỗi, chưa sửa**;
kết quả smoke run **chưa được ghi lại**; các mục metrics/so sánh/robustness/performance/
tuning/error-analysis và báo cáo **CHƯA làm**. Working tree hiện có 2 file sửa chưa commit
(`.github/workflows/ci.yml`, `pyproject.toml`) — giữ nguyên, commit chung với việc của vòng này.

## Việc cần làm, theo thứ tự

1. **Đọc tình trạng đầu vào:** `mlai-p8-continue.log` (toàn bộ), `git status`, `git log --oneline -5`,
   `git diff --stat`. Xác nhận branch `p8-review`, HEAD `2086dab`.
2. **Sửa hết 15 lỗi ruff trong `benchmark/`** (E501 dòng dài, UP037 annotation có quote, và các lỗi còn lại).
   Chạy `.venv/bin/python -m ruff check benchmark` — **KHÔNG pipe qua `tail`/`head`**, ghi log ra file,
   đọc exit code (`$?`). Dùng `--fix` chỗ nào an toàn, còn lại sửa tay. Chạy lại tới khi ruff sạch.
   Sau đó `.venv/bin/python -m mypy benchmark` (cũng không pipe) tới khi sạch.
3. **Xác định kết quả smoke run:** tìm artifact/kết quả smoke của vòng 1 (output, file kết quả, log).
   Nếu không có bằng chứng nó đã chạy xong thì chạy lại:
   `timeout 1500 .venv/bin/python -m benchmark.run --split dev --tag smoke`
   (không pipe; ghi log ra file). Ghi rõ pass/fail + số liệu vào báo cáo.
4. **Hoàn thiện các mục P8 còn lại** theo plan P8 (file prompt P8 trong `~/workspace/aws-quick/prompts_aws_quick.md`
   dòng 441–500 — đọc lại nếu cần, nhưng file này nằm trên VM, không có trên LV3; tóm tắt các mục:
   metrics + so sánh các backend, robustness, performance, tuning (nếu có gì đáng tune),
   error analysis): chạy các lệnh cần thiết, ghi số liệu thật vào báo cáo.
   - Qwen2.5-VL local: KHÔNG chạy được trên LV3 (thiếu RAM/đĩa) — ghi là not-run kèm lý do, đừng cố tải.
   - Gemini Vision: OFF (không có key) — ghi là not-run.
   - Seed dataset chỉ có 35 mẫu, eval render scene từ seed JSON lúc chạy (ảnh placeholder 1×1) —
     mọi số liệu phải ghi rõ điều này, không nói như thể đo trên ảnh thật.
5. **Viết báo cáo:** `docs/reports/benchmark_report.md` + `P8_REPORT.md` (gốc repo) với số liệu thật
   từ vòng này (smoke, metrics, robustness, performance, CI gate), kèm mục "chưa làm / not-run" trung thực.
6. **Kiểm chứng đầy đủ, KHÔNG pipe, ghi log ra file, đọc exit code từng lệnh:**
   - Full pytest: `.venv/bin/python -m pytest -q` (không pipe; pytest -q trên setup này không in dòng
     tóm tắt — kết luận bằng exit code + không có dòng FAILED).
   - Validate seed: `.venv/bin/python -m benchmark.validate` (kỳ vọng 35/35).
   - `ruff check` toàn repo + `mypy engine benchmark`.
   - Industrial eval + validation eval (lấy số routing/F1 hiện tại để đối chiếu, không cần cải thiện).
   Tất cả phải xanh mới được coi là xong. Nếu một check đỏ mà hết lượt, ghi rõ check nào đỏ + lỗi gì
   vào REPORT, commit phần đã làm, KHÔNG giấu.
7. **Commit + push trên `p8-review`** (LV3 push được qua `.git-credentials`): gom toàn bộ thay đổi
   (kể cả 2 file của vòng 1) thành 1 commit, message rõ ràng, rồi `git push`. **KHÔNG merge sang main**
   (liaison merge sau khi review + test độc lập).
8. **Báo cáo cuối vòng:** ghi tóm tắt vào cuối `mlai-p8-continue2.log` (hoặc file REPORT trong repo):
   đã làm gì, số liệu chính, còn thiếu gì, blocker nào (nếu có, viết `BLOCKED.md` và DỪNG ở đó,
   không tự chuyển sang phase khác).

## Luật bắt buộc

- Mọi lệnh kiểm chứng (pytest/ruff/mypy/eval) chạy TRẦN, ghi log ra file, đọc `$?`.
  **CẤM pipe `| tail` / `| head` sau lệnh kiểm** — pipe che mất exit code, fail vẫn hiện như pass.
  Lỗi "check failed" do pipe là báo động giả, không tin.
- KHÔNG tạo file test mới, KHÔNG cài thêm package (jiwer/matplotlib đã có).
- KHÔNG sửa file ngoài phạm vi P8 (benchmark/, docs/reports/, P8_REPORT.md, ci.yml, pyproject.toml).
- Model mặc định đã là mạnh nhất — không truyền cờ `-m`.
- Nếu hết lượt giữa chừng: commit phần đã xong + push, ghi rõ mục còn lại cho vòng sau.
  Không để working tree dơ mà không commit.
