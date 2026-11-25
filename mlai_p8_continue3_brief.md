# Brief: Image Engine P8 — vòng tiếp nối 3 (viết báo cáo + kiểm chứng đầy đủ + commit)

Bạn làm việc trên LV3 (hermes-wb), repo `/root/image-extraction-engine`, branch **`p8-review`**.
Main đã merge xong (HEAD `2086dab`) — **KHÔNG merge main nữa, KHÔNG merge sang main.**

## Tình trạng vòng 2 (đọc log trước khi làm)

Vòng 2 (log `mlai-p8-continue2.log`, dừng ở "Done · 1.3 credits · 123 model calls",
còn 4 bước mở) đã làm được:
- Sửa hết 15 lỗi ruff: `ruff check benchmark` đã PASSED.
- Smoke run chạy xong, artifact thật ở `benchmark/artifacts/smoke_2086dab8/`
  (config.json, errors.json, metrics.json, performance.json).
- Đã viết `docs/reports/p8_benchmark.md` (đang untracked).
- Chưa làm: 2 báo cáo còn lại, kiểm chứng đầy đủ, commit + push.

Working tree hiện tại (chưa commit gì): sửa `ci.yml`, `pyproject.toml`,
`benchmark/harness.py`, `benchmark/robustness.py`, `benchmark/run.py`;
untracked `benchmark/artifacts/`, `docs/reports/p8_benchmark.md`,
2 file brief. Giữ nguyên tất cả, commit chung với việc của vòng này.

Lưu ý trung thực từ vòng 2 (ghi vào báo cáo, không giấu):
- Baseline run trước lần sửa đầu bị dừng ở giới hạn thời gian — chỉ so sánh
  được phần nó chạy tới, KHÔNG phải so sánh đầy đủ.
- `benchmark/run.py:253` có thêm `# type: ignore[assignment]` — xem lại lỗi
  thật bên dưới, sửa gốc nếu được, nếu buộc phải giữ thì ghi rõ lý do.
- Các chart PNG trong artifact chưa từng mở xem — chỉ cần số liệu trong
  metrics.json/performance.json, không cần xem ảnh.

## Việc cần làm, theo thứ tự

1. **Đọc tình trạng đầu vào:** toàn bộ `mlai-p8-continue2.log`,
   `git status`, `git log --oneline -5`, `docs/reports/p8_benchmark.md`,
   `benchmark/artifacts/smoke_2086dab8/metrics.json` và `performance.json`.
2. **Viết 2 báo cáo còn thiếu từ số liệu thật của artifact:**
   - `P8_REPORT.md` (gốc repo) — tóm tắt P8: smoke, metrics, robustness,
     performance, CI gate, kết luận + mục chưa làm/not-run.
   - `docs/reports/benchmark_report.md` — báo cáo benchmark đầy đủ.
   - Ghi rõ: seed chỉ 35 mẫu, eval render scene từ seed JSON lúc chạy
     (ảnh placeholder 1×1), KHÔNG phải ảnh thật; Qwen2.5-VL local not-run
     (LV3 thiếu RAM/đĩa); Gemini Vision OFF (không key); so sánh baseline
     chỉ một phần (vòng 2 dừng giữa chừng). Số liệu nào không đo được thì
     ghi "chưa đo", không bịa, không làm tròn đẹp lên.
3. **Kiểm chứng đầy đủ, KHÔNG pipe, ghi log ra file, đọc exit code từng lệnh:**
   - Full pytest: `.venv/bin/python -m pytest -q` (pytest -q trên setup này
     không in dòng tóm tắt — kết luận bằng exit code + không có dòng FAILED).
   - Validate seed: `.venv/bin/python -m benchmark.validate` (kỳ vọng 35/35).
   - `ruff check` toàn repo + `mypy engine benchmark`.
   - Industrial eval + validation eval (lấy số routing/F1 hiện tại để đối chiếu).
   Tất cả phải xanh mới được coi là xong. Nếu một check đỏ mà hết lượt, ghi rõ
   check nào đỏ + lỗi gì vào P8_REPORT.md, commit phần đã làm, KHÔNG giấu.
4. **Xử lý `run.py:253` type-ignore:** sửa lỗi gốc nếu sửa được trong vòng này;
   nếu không, giữ suppression và ghi rõ lý do vào P8_REPORT.md.
5. **Commit + push trên `p8-review`** (LV3 push được qua `.git-credentials`):
   gom toàn bộ thay đổi (kể cả file của vòng 1 + vòng 2) thành commit(s) rõ ràng,
   rồi `git push`. **KHÔNG merge sang main** (liaison merge sau khi review + test).
6. **Báo cáo cuối vòng:** ghi tóm tắt vào cuối `mlai-p8-continue3.log`:
   đã làm gì, số liệu chính, còn thiếu gì, blocker nào (nếu có, viết `BLOCKED.md`
   và DỪNG ở đó, không tự chuyển sang phase khác).

## Luật bắt buộc

- Mọi lệnh kiểm chứng (pytest/ruff/mypy/eval) chạy TRẦN, ghi log ra file, đọc `$?`.
  **CẤM pipe `| tail` / `| head` sau lệnh kiểm** — pipe che mất exit code, fail vẫn
  hiện như pass. Lỗi "check failed" do pipe là báo động giả, không tin.
- KHÔNG tạo file test mới, KHÔNG cài thêm package.
- KHÔNG sửa file ngoài phạm vi P8 (benchmark/, docs/reports/, P8_REPORT.md, ci.yml,
  pyproject.toml).
- Model mặc định đã là mạnh nhất — không truyền cờ `-m`.
- Nếu hết lượt giữa chừng: commit phần đã xong + push, ghi rõ mục còn lại cho vòng sau.
  Không để working tree dơ mà không commit.
