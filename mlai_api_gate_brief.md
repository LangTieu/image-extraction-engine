# Brief: API key gate — bật cổng mật khẩu cho OCR API (branch api-gate)

## Bối cảnh
- API ocr.aistockvn.com hiện MỞ CÔNG KHAI, không mật khẩu. Henrry đã Chốt: BẬT cổng mật khẩu.
- Backend ĐÃ CÓ middleware: `service/api/app.py:55-62` — khi env `IMAGE_ENGINE_API_KEY` non-empty thì mọi gọi `/v1/*` (trừ `/v1/health`) đều đòi header `X-API-Key`, sai/thiếu → 401. `service/core/settings.py:41-43`: `api_key_env = "IMAGE_ENGINE_API_KEY"`, empty = auth off (dev default, giữ nguyên cho local).
- UI CHƯA CÓ chỗ nhập key (v0 prompt cấm auth UI). `service/web/src/api.ts`: mọi gọi API đi qua `request()` dòng 240 (fetch) + 1 chỗ upload XHR dòng 828.
- Compose: dòng `IMAGE_ENGINE_API_KEY` đang comment trong `docker-compose.yml` (environment của api).
- Deploy: `.github/workflows/deploy.yml` chạy `IMAGE_TAG=${{ github.sha }} docker compose up -d --no-build`, chưa truyền secret.

## Việc cần làm
1. **UI — màn hình mở khóa + gửi key** (`service/web/src`, giữ giao diện hiện tại):
   - Lần đầu mở web (chưa có key) hoặc khi API trả 401 → hiện màn hình mở khóa: 1 ô nhập key (dạng password) + nút mở khóa. Key lưu vào localStorage (tên rõ ràng, vd `iee_api_key`).
   - `api.ts`: `request()` và XHR upload đều gắn header `X-API-Key` từ localStorage vào MỌI gọi API. `/v1/health` không cần key (đèn "API online" vẫn dùng được).
   - 401 → xóa key đã lưu, quay lại màn hình mở khóa với thông báo key sai/hết hạn.
   - Thêm nút nhỏ đổi key / đăng xuất (vd ở cuối sidebar).
   - TUYỆT ĐỐI KHÔNG hardcode bất kỳ giá trị key nào vào bundle, code, test hay compose. Key thật do liaison cấp qua GitHub secret tên `IMAGE_ENGINE_API_KEY` — vòng này KHÔNG tạo, KHÔNG ghi giá trị key nào.
2. **docker-compose.yml**: bỏ comment, đặt `IMAGE_ENGINE_API_KEY: ${IMAGE_ENGINE_API_KEY:-}` trong environment của api. Để trống thì auth vẫn tắt ở local (dev default như cũ).
3. **.github/workflows/deploy.yml**: truyền secret vào bước deploy: `IMAGE_ENGINE_API_KEY=${{ secrets.IMAGE_ENGINE_API_KEY }} IMAGE_TAG=${{ github.sha }} docker compose up -d --no-build`. Thêm 1 guard step TRƯỚC bước deploy: fail run ngay nếu secret rỗng (để secret thiếu không bao giờ deploy lặng lẽ 1 API mở toang).
4. **Test — CHỈ trong file test ĐÃ CÓ (không tạo file test mới)**:
   - Backend: đặt `IMAGE_ENGINE_API_KEY` (monkeypatch, đọc code xem middleware lấy key lúc nào — per-request hay import-time — rồi viết test cho đúng): không key → 401 ở `GET /v1/jobs`; đúng key → 200; `/v1/health` → 200 không cần key.
   - UI contract test (mở rộng parser `_collect_ui_calls` trong `tests/test_api.py` như vòng v0): api.ts gửi header `X-API-Key` khi có key lưu.
   - Ghi bằng chứng fail trước fix (chạy test mới trên code chưa sửa phải FAIL) vào report.
5. **Report**: `API_GATE_REPORT.md` ở repo root — đổi gì, cách xoay key (đổi GitHub secret → redeploy, không bao giờ ghi vào repo), bằng chứng kiểm chứng.

## Quy trình
- Branch: `api-gate`, tạo từ main mới nhất (`71bcf6b`). Làm việc TRÊN BRANCH, không làm trên main.
- KHÔNG push, KHÔNG deploy — liaison làm bước đó sau khi kiểm chứng độc lập.
- Chạy kiểm chứng KHÔNG pipe qua tail/head (ghi log ra file, đọc exit code): pytest, validate 35/35, ruff, mypy, `npm run build` trong service/web.
- Commit gọn trên branch khi xong. Báo cáo cuối: số test, exit code từng bước, file đổi.
