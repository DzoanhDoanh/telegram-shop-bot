# Telegram Bot Sales UX Option A Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Telegram bot feel production-ready for buyers by adding persistent menu buttons, clearer sales copy, support/help commands, and new-product announcements.

**Architecture:** Keep aiogram handlers and existing database schema. Add reusable user keyboard helpers and a best-effort notification service. Register Telegram commands on bot startup. Touch existing handlers with targeted UX changes only.

**Tech Stack:** Python, aiogram 3, SQLAlchemy async, FastAPI web admin integration.

---

## Files and responsibilities

- Modify `app/keyboards/user_kb.py`: persistent reply keyboard, polished inline keyboards.
- Modify `app/handlers/user/start.py`: `/start`, `/shop`, `/help`, `/support`, reply-keyboard text handlers.
- Modify `app/handlers/user/catalog.py`: polished catalog/product messages, stock-aware CTA.
- Modify `app/handlers/user/checkout.py`: polished payment flow, support button.
- Modify `app/handlers/user/orders.py`: polished order list with product eager load.
- Create `app/services/notification_service.py`: best-effort new product announcement.
- Modify `app/web/main.py`: notify users after admin adds product.
- Modify `run.py`: register bot commands on startup.
- Modify `docs/run-guide.md`: mention persistent menu and Redis/Postgres local requirement.

## Scope

Included:
- Persistent reply keyboard near chat input.
- Bot commands.
- Better user-facing messages.
- Product announcement after web admin adds product.
- No DB schema changes.

Excluded:
- Broadcast queue.
- Opt-in/out.
- Payment reminders.
- Coupons.
- Analytics.

---

### Task 1: User keyboard helpers

**Files:**
- Modify: `app/keyboards/user_kb.py`

Steps:
- [ ] Add reply keyboard imports:

```python
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup
```

- [ ] Add constants:

```python
BTN_SHOP = "🛍 Mua hàng"
BTN_ORDERS = "📦 Đơn hàng của tôi"
BTN_SUPPORT = "💬 Hỗ trợ"
BTN_HELP = "❓ Hướng dẫn"
```

- [ ] Add persistent reply keyboard:

```python
def get_persistent_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_SHOP), KeyboardButton(text=BTN_ORDERS)],
            [KeyboardButton(text=BTN_SUPPORT), KeyboardButton(text=BTN_HELP)],
        ],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Chọn thao tác bên dưới...",
    )
```

- [ ] Keep `get_main_menu_kb()` for inline buttons, but polish labels:
  - `🛍 Xem sản phẩm`
  - `📦 Đơn hàng của tôi`
  - `💬 Hỗ trợ`

Verification:
- [ ] `python -m compileall app/keyboards/user_kb.py`

### Task 2: Start/help/support/shop commands and reply buttons

**Files:**
- Modify: `app/handlers/user/start.py`

Steps:
- [ ] Import `Command` and constants/helper from `user_kb.py`.
- [ ] Extract `ensure_user(message)` helper for user creation + ban check.
- [ ] Add `send_welcome(message)` with production-ready welcome copy and `reply_markup=get_persistent_menu_kb()`.
- [ ] Keep `/start` using `send_welcome`.
- [ ] Add `/help` handler and reply button `BTN_HELP` handler:
  - Explain 4 steps: choose product, transfer, send bill, receive digital goods.
- [ ] Add `/support` handler and reply button `BTN_SUPPORT` handler:
  - If `SHOP_SUPPORT_USERNAME`, send t.me link.
  - Else tell user to reply with issue.
- [ ] Add `/shop` handler and reply button `BTN_SHOP` handler:
  - Send/trigger catalog view with inline category buttons.
- [ ] Add reply button `BTN_ORDERS` handler that delegates to order list display.

Implementation note:
- To avoid circular imports, create small public functions in catalog/orders tasks if needed. If not available yet, route by sending callback-style functions is not required; duplicate small query logic is acceptable only if concise.

Verification:
- [ ] `python -m compileall app/handlers/user/start.py`

### Task 3: Catalog and product message polish

**Files:**
- Modify: `app/handlers/user/catalog.py`

Steps:
- [ ] Add public function `send_catalog(message: types.Message)` that queries categories and sends category inline keyboard.
- [ ] Existing `show_categories(callback)` should call same builder logic and edit callback message.
- [ ] Polish category message:
  - title `🛍 <b>Chọn danh mục sản phẩm</b>`
  - short sales copy.
- [ ] Product list buttons show name + price.
- [ ] Product detail:
  - escape/safely format name/description if needed.
  - Show stock status clearly.
  - If stock > 0, show buy + support + back buttons.
  - If stock == 0, show support + back only.
- [ ] Friendly unavailable messages.

Verification:
- [ ] `python -m compileall app/handlers/user/catalog.py`

### Task 4: Checkout and orders message polish

**Files:**
- Modify: `app/handlers/user/checkout.py`
- Modify: `app/handlers/user/orders.py`

Steps:
- [ ] Checkout payment message should include:
  - order id;
  - product name;
  - amount;
  - bank name/account/name;
  - required transfer content `DH{order.id}`;
  - warning to transfer exact amount/content;
  - instruction to send screenshot.
- [ ] Checkout inline keyboard should include:
  - `❌ Hủy đơn hàng`
  - `💬 Hỗ trợ`
- [ ] After proof received, confirmation message should include order id and expected admin verification.
- [ ] Admin notification should include product/order amount if available.
- [ ] Orders list should eager load product and show:
  - order id;
  - product name;
  - total amount;
  - created date;
  - status.
- [ ] Add public function `send_user_orders(message: types.Message)` for command/reply button reuse.

Verification:
- [ ] `python -m compileall app/handlers/user/checkout.py app/handlers/user/orders.py`

### Task 5: Product announcement service and web hook

**Files:**
- Create: `app/services/notification_service.py`
- Modify: `app/web/main.py`

Steps:
- [ ] Create notification service:

```python
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database.models import Product, User

MAX_PRODUCT_ANNOUNCEMENTS = 200

async def announce_new_product(bot: Bot | None, session, product_id: int) -> int:
    if bot is None:
        return 0
    product = await session.get(Product, product_id, options=[selectinload(Product.category)])
    if not product or not product.is_active:
        return 0
    result = await session.execute(
        select(User.id).where(User.is_banned == False).limit(MAX_PRODUCT_ANNOUNCEMENTS)
    )
    user_ids = list(result.scalars().all())
    sent = 0
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Xem sản phẩm", callback_data=f"prod_{product.id}")]
    ])
    text = (
        "🆕 <b>Sản phẩm mới vừa lên kệ!</b>\n\n"
        f"📦 <b>{product.name}</b>\n"
        f"💰 Giá: <b>{product.price:,.0f}đ</b>\n"
        f"🏷 Danh mục: {product.category.name if product.category else 'Khác'}\n\n"
        "Bấm nút bên dưới để xem chi tiết và mua ngay."
    )
    for user_id in user_ids:
        try:
            await bot.send_message(user_id, text, reply_markup=kb)
            sent += 1
        except Exception:
            continue
    return sent
```

- [ ] In `app/web/main.py`, after product add commit/refresh succeeds, call `announce_new_product(_bot, session, product.id)` best-effort.
- [ ] Do not fail product creation if announcement fails.

Verification:
- [ ] `python -m compileall app/services/notification_service.py app/web/main.py`

### Task 6: Register bot commands on startup

**Files:**
- Modify: `run.py`

Steps:
- [ ] Import `BotCommand`.
- [ ] Add helper:

```python
async def set_bot_commands(bot: Bot) -> None:
    await bot.set_my_commands([
        BotCommand(command="start", description="Mở menu chính"),
        BotCommand(command="shop", description="Xem sản phẩm"),
        BotCommand(command="orders", description="Đơn hàng của tôi"),
        BotCommand(command="support", description="Liên hệ hỗ trợ"),
        BotCommand(command="help", description="Hướng dẫn mua hàng"),
    ])
```

- [ ] Call `await set_bot_commands(bot)` before polling.

Verification:
- [ ] `python -m compileall run.py`

### Task 7: Run guide update and final verification

**Files:**
- Modify: `docs/run-guide.md`

Steps:
- [ ] Add note: bot now has persistent Telegram menu next to chat input.
- [ ] Add local requirement reminder: Redis and PostgreSQL must be running for `python run.py`.
- [ ] Add quick Telegram UX verification list.
- [ ] Run final compile:

```powershell
python -m compileall app run.py
```

- [ ] Search for obvious syntax issues in changed files.
- [ ] Read lints for changed Python files.

---

## Handoff notes

- Keep Phase 1 safe delivery service unchanged.
- Product notification is best-effort and limited to 200 users in MVP.
- Persistent reply keyboard should be sent with `/start` and key entry messages so users see menu near chat input.
