# Telegram Digital Shop Bot — Web Admin Design Specification

## Goal

Hoàn thiện Telegram digital shop bot bằng web admin panel theo hướng chạy ổn trước, mở rộng sau. Code hiện đã có FastAPI/Jinja admin khung cơ bản, nên thiết kế tập trung sửa các điểm rủi ro trong luồng bán hàng: đăng nhập admin, duyệt đơn, giao key, xem bill, Docker/local run.

## Current state

Đã có:

- `app/web/main.py` với routes login, dashboard, orders, products, inventory.
- `app/web/templates/` với `base.html`, `login.html`, `dashboard.html`, `orders.html`, `products.html`, `inventory.html`.
- `requirements.txt` đã có `fastapi`, `uvicorn`, `jinja2`, `python-multipart`.
- `run.py` chạy Telegram bot và FastAPI web admin cùng lúc.
- `ADMIN_PASSWORD` trong `app/config.py`.

Vấn đề cần sửa trước khi coi là shop tự động ổn định:

- Cookie auth đang lưu trực tiếp `ADMIN_PASSWORD`.
- Approve order đang set `COMPLETED` trước khi giao key; nếu hết kho hoặc Telegram gửi lỗi thì trạng thái sai.
- Bill ảnh cần xử lý đúng Telegram `file_id`/`file_path` để web xem được.
- Docker compose chưa expose web port `8000`.
- Product/inventory workflow còn thiếu edit/delete/category/duplicate protection.
- Web chưa có CSRF, rate limit, audit log.

## Recommended phase plan

### Phase 1 — Stabilize MVP

Mục tiêu: admin web dùng được để bán hàng thật với rủi ro thấp.

Scope:

- Đổi auth cookie sang session/token ký bằng secret, không lưu thẳng password.
- Thêm `SESSION_SECRET` vào config/env example.
- Sửa approve order thành luồng an toàn:
  - kiểm tra order còn `pending_payment`;
  - kiểm tra đủ inventory chưa bán;
  - gửi key qua Telegram;
  - chỉ khi gửi thành công mới mark inventory sold và set order `COMPLETED`;
  - nếu thiếu kho hoặc gửi lỗi thì giữ order pending, không trừ kho.
- Sửa xem bill:
  - resolve Telegram file từ `payment_proof` nếu đang lưu `file_id`;
  - hiển thị link/thumbnail an toàn cho admin;
  - nếu không resolve được thì hiển thị placeholder.
- Cập nhật Docker/local run:
  - expose port `8000` cho service bot/web;
  - giữ `python run.py` là entrypoint chính chạy bot + web.
- Verification tối thiểu:
  - compile Python;
  - login sai/đúng;
  - thêm product;
  - nhập inventory;
  - approve order đủ kho;
  - approve order thiếu kho;
  - reject order;
  - Docker compose thấy port web.

### Phase 2 — Admin workflow

Mục tiêu: nhập liệu nhanh, giảm lỗi vận hành.

Scope:

- Product management:
  - edit product;
  - soft delete/disable product;
  - chọn category khi tạo/sửa;
  - search/filter product table.
- Inventory management:
  - chống nhập trùng key theo `product_id + content`;
  - báo số dòng hợp lệ, dòng trùng, dòng rỗng;
  - xem tồn kho theo sản phẩm;
  - cảnh báo tồn kho thấp.
- Order management:
  - filter theo trạng thái, ngày, sản phẩm;
  - reject có lý do;
  - confirm modal trước approve/reject.

### Phase 3 — Security & Ops

Mục tiêu: đủ chắc để public sau reverse proxy.

Scope:

- CSRF cho toàn bộ POST.
- Login rate limit.
- Cookie flags: `httponly`, `samesite`, `secure` theo môi trường.
- Audit log:
  - admin login/logout;
  - approve/reject order;
  - add/edit/delete product;
  - add inventory.
- Export CSV:
  - orders;
  - products;
  - inventory summary.
- Deploy checklist và backup notes.

### Phase 4 — Polish UI

Mục tiêu: nâng UX nhưng không phá luồng đã ổn.

Scope:

- Responsive sidebar cho mobile/tablet.
- Modal xem bill inline.
- Toast thay query-string `msg`.
- Empty states tốt hơn.
- Loading/disabled state cho approve/reject.
- Giữ visual direction: Slate/Emerald, Inter, rounded-2xl, glassmorphism nhẹ, không dùng violet/purple.

## Architecture

Giữ stack hiện tại:

- FastAPI
- Jinja2
- Tailwind CDN
- Chart.js
- SQLAlchemy async
- aiogram Bot

Không đổi sang React/Next ở giai đoạn này. Admin panel server-rendered đủ nhanh, ít build/deploy complexity, phù hợp dự án nhỏ.

Tách code dần để dễ bảo trì:

```text
app/web/
├── auth.py
├── dependencies.py
├── main.py
├── routes/
│   ├── dashboard.py
│   ├── orders.py
│   ├── products.py
│   └── inventory.py
└── templates/
```

Phase 1 có thể sửa trong cấu trúc hiện tại nếu ít thay đổi. Từ Phase 2 nên tách route vì `app/web/main.py` đang gom nhiều trách nhiệm.

## Critical data flow: approve order

Luồng approve mới:

1. Admin bấm approve.
2. Server load order kèm product/user.
3. Nếu order không còn `pending_payment`, trả flash message lỗi.
4. Query inventory chưa bán đủ số lượng.
5. Nếu thiếu hàng, trả flash message lỗi, order giữ `pending_payment`.
6. Build delivery message chứa key.
7. Gửi Telegram message cho user.
8. Nếu Telegram gửi thành công:
   - mark inventory sold;
   - gán `order_id` cho inventory items;
   - set `order.status = COMPLETED`;
   - set `paid_at` và `completed_at`;
   - commit.
9. Nếu Telegram gửi lỗi:
   - rollback;
   - order giữ `pending_payment`;
   - báo admin có thể retry.

Design choice: không mark completed trước khi giao key, vì trạng thái đơn phải phản ánh kết quả giao hàng thật.

## Error handling

- Thiếu hàng: hiển thị lỗi trên web, không đổi trạng thái đơn.
- Telegram fail: giữ đơn pending, admin có thể retry.
- Bill không load được: hiển thị placeholder và thông tin debug ngắn cho admin.
- Auth fail: redirect login.
- Form invalid: redirect kèm flash message.
- Duplicate inventory: Phase 2 skip dòng trùng và báo summary.

## Verification plan

Phase 1:

- Run `python -m compileall app run.py`.
- Start local app with `python run.py` if env/db/redis available.
- Test `/login` wrong and correct password.
- Create product from web admin.
- Add three inventory items.
- Create or seed one pending order.
- Approve order with enough stock and verify Telegram delivery behavior.
- Approve order with insufficient stock and verify order remains pending.
- Reject order and verify status/message.
- Check `docker-compose.yml` exposes web port `8000`.

Phase 2:

- Edit/delete product without breaking old orders.
- Bulk inventory skips duplicates.
- Search/filter returns expected rows.
- Reject reason appears in Telegram message.

Phase 3:

- POST without CSRF fails.
- Cookie never contains admin password.
- Login rate limit triggers after repeated failures.
- Audit log records key admin actions.

Phase 4:

- Layout works on desktop/tablet/mobile.
- Bill modal opens/closes.
- Toasts show success/error.
- No purple/violet classes added.

## Out of scope for current phase plan

- React/Next.js rewrite.
- Multi-admin roles/permissions.
- Automated bank transfer reconciliation.
- Public customer web storefront.
- Payment gateway integration.

These can be future projects after web admin MVP is stable.
