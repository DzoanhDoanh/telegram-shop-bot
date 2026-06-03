# Telegram Bot Sales UX Design

## Goal

Nâng trải nghiệm bot Telegram để người mua dễ thao tác, thấy menu liên tục cạnh thanh chat, hiểu rõ quy trình mua hàng, và tăng khả năng shop vận hành bán thật.

## Scope: Option A — Safe MVP

Triển khai các cải thiện ít rủi ro, không đổi database schema, không thêm hệ thống marketing phức tạp.

Included:

- Persistent reply keyboard luôn hiện cạnh thanh chat:
  - `🛍 Mua hàng`
  - `📦 Đơn hàng của tôi`
  - `💬 Hỗ trợ`
  - `❓ Hướng dẫn`
- Bot commands:
  - `/start`
  - `/shop`
  - `/orders`
  - `/support`
  - `/help`
- Welcome message chuyên nghiệp hơn.
- Catalog/category/product messages rõ hơn, đẹp hơn, có CTA mua hàng.
- Checkout/payment message rõ ràng hơn:
  - mã đơn;
  - sản phẩm;
  - số tiền;
  - tài khoản nhận;
  - nội dung chuyển khoản bắt buộc;
  - hướng dẫn gửi bill;
  - nút hủy đơn và hỗ trợ.
- Orders message hiển thị sản phẩm, ngày, số tiền, trạng thái.
- Help message hướng dẫn mua hàng 4 bước.
- Support handler trả về link support.
- Khi admin thêm sản phẩm từ web admin, bot thông báo sản phẩm mới cho users đã từng dùng bot.

Excluded:

- Broadcast queue nâng cao.
- Opt-in/opt-out.
- Abandoned payment reminders.
- Discount/coupon campaigns.
- Analytics dashboard.
- Database migrations.
- Payment gateway integration.

## Current code points

- `app/handlers/user/start.py`: xử lý `/start`.
- `app/handlers/user/catalog.py`: category/product browsing.
- `app/handlers/user/checkout.py`: create order, payment proof flow.
- `app/handlers/user/orders.py`: user order list.
- `app/keyboards/user_kb.py`: main inline keyboard.
- `app/web/main.py`: web admin product add route can trigger product notification.
- `run.py`: bot startup can register bot commands.

## Proposed architecture

Keep current aiogram/FastAPI structure.

Add focused Telegram UX helpers instead of scattering text everywhere:

```text
app/
├── keyboards/
│   └── user_kb.py          # inline buttons + persistent reply keyboard
├── services/
│   └── notification_service.py  # product announcement broadcast best-effort
└── handlers/user/
    ├── start.py            # start/help/support/shop command + reply keyboard text triggers
    ├── catalog.py          # polished catalog/product messages
    ├── checkout.py         # polished payment flow
    └── orders.py           # polished order list
```

## UX behavior

### Persistent menu

Every user-facing entry point sends messages with a persistent reply keyboard so buttons stay near chat input.

Reply keyboard button handling:

- `🛍 Mua hàng` behaves like `/shop`.
- `📦 Đơn hàng của tôi` behaves like `/orders`.
- `💬 Hỗ trợ` behaves like `/support`.
- `❓ Hướng dẫn` behaves like `/help`.

### Product flow

1. User taps `🛍 Mua hàng`.
2. Bot shows active categories.
3. User picks category.
4. Bot shows active products in category with price.
5. User picks product.
6. Bot shows detail:
   - name;
   - description;
   - price;
   - stock;
   - fulfillment note;
   - buy/support/back buttons.

If out of stock, show clear unavailable state and no buy button.

### Checkout flow

1. User taps buy.
2. Bot checks product exists and stock > 0.
3. Bot creates pending order.
4. Bot shows bank transfer instructions.
5. User sends payment screenshot.
6. Bot confirms receipt and tells user admin will verify.
7. Admin approves from web/Telegram.
8. Existing safe delivery service sends digital goods.

### Product announcement

When admin adds product in web admin:

- Send announcement to users in `users` table who are not banned.
- Message includes product name, price, category, short description, and button to view product.
- Best-effort: failures are ignored per user so one bad chat does not break admin action.
- To avoid huge blocking jobs, limit announcement to first 200 active users in this MVP.

## Error handling

- If support username missing, show text asking user to reply with issue instead of broken URL.
- If product missing/inactive/out of stock, show friendly unavailable message and back button.
- If notification send fails for a user, skip and continue.
- If bot instance is unavailable in web admin, product add still succeeds but no notification is sent.

## Verification plan

- `python -m compileall app run.py`
- Start bot with Redis/Postgres available.
- `/start` shows persistent keyboard.
- Reply keyboard buttons trigger expected flows.
- `/shop`, `/orders`, `/help`, `/support` work.
- Browse category/product detail.
- Buy product creates order and shows polished payment message.
- Send payment screenshot and admin gets notification.
- Add product from web admin and verify users receive announcement.
- Verify no existing web admin CSRF/session/order delivery behavior breaks.

## Future Phase 6 candidates

- Broadcast queue with rate limits.
- Opt-in/opt-out marketing preferences.
- Pending payment reminders.
- Coupons/discount codes.
- Sales analytics.
