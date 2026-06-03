# Telegram Shop Web Admin Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stabilize the existing FastAPI/Jinja web admin so a Telegram shop selling digital goods (keys, accounts, file access info) can safely approve orders, deliver inventory, and run locally/Docker without corrupting order state.

**Architecture:** Keep the existing Python/FastAPI/Jinja stack and make focused Phase 1 fixes without a broad route refactor. Move delivery correctness into `app/services/delivery_service.py` and `app/services/order_service.py`, keep web routes thin, and use signed session tokens instead of storing the admin password in cookies.

**Tech Stack:** Python 3.11, FastAPI, Jinja2, SQLAlchemy async, aiogram, PostgreSQL, Redis, Docker Compose.

---

## Files and responsibilities

- Modify `app/config.py`: add `SESSION_SECRET`, `WEB_HOST`, `WEB_PORT`, and cookie security settings with safe defaults.
- Modify `.env.example`: document new web/session config values.
- Modify `app/web/auth.py`: implement signed admin session cookie helpers.
- Modify `app/web/main.py`: use signed auth helpers, route approve/reject through safe service methods, add bill URL route/helper.
- Modify `app/services/delivery_service.py`: add atomic digital-goods delivery logic for text inventory items (keys/accounts/file links stored in `InventoryItem.content`).
- Modify `app/services/order_service.py`: keep create/update/reject, replace unsafe approve workflow with safe status helpers or call delivery service from handlers.
- Modify `app/handlers/admin/orders.py`: Telegram admin approval must use same safe delivery logic as web approval.
- Modify `app/web/templates/orders.html`: change bill link to internal route, show safer status/error text if needed.
- Modify `run.py`: use configurable web host/port and keep shared bot instance.
- Modify `Dockerfile`: run `python run.py` instead of old `app/main.py`.
- Modify `docker-compose.yml`: expose web port `8000:8000` and keep bot service dependencies.

## Phase 1 constraints

- Digital goods delivery in Phase 1 means text secrets stored in `InventoryItem.content`: product keys, account credentials, download links, or file access instructions. Binary file upload/storage is out of scope for Phase 1.
- Do not add React/Next or build tooling.
- Do not implement Phase 2 features such as edit product, duplicate inventory protection, CSRF, audit log, or search/filter unless needed to fix Phase 1 safety.
- Do not commit unless user explicitly asks.

---

### Task 1: Session config and signed cookie auth

**Files:**
- Modify: `app/config.py`
- Modify: `.env.example`
- Modify: `app/web/auth.py`

- [ ] **Step 1: Update config settings**

Edit `app/config.py` so the `Settings` class includes session and web server config. Preserve existing settings.

```python
from decouple import config

class Settings:
    BOT_TOKEN = config('BOT_TOKEN', default='')
    ADMIN_IDS = [int(id.strip()) for id in config('ADMIN_IDS', default='').split(',') if id.strip()]
    ADMIN_PASSWORD = config('ADMIN_PASSWORD', default='admin_secret')
    SESSION_SECRET = config('SESSION_SECRET', default='change_me_session_secret')
    SESSION_COOKIE_SECURE = config('SESSION_COOKIE_SECURE', default=False, cast=bool)
    WEB_HOST = config('WEB_HOST', default='127.0.0.1')
    WEB_PORT = config('WEB_PORT', default=8000, cast=int)

    DATABASE_URL = config('DATABASE_URL', default='postgresql+asyncpg://shopbot:shopbot_secret@localhost:5432/shopbot')
    REDIS_URL = config('REDIS_URL', default='redis://localhost:6379/0')

    BANK_NAME = config('BANK_NAME', default='Vietcombank')
    BANK_ACCOUNT_NO = config('BANK_ACCOUNT_NO', default='')
    BANK_ACCOUNT_NAME = config('BANK_ACCOUNT_NAME', default='')
    VIETQR_URL = config('VIETQR_URL', default='')

    SHOP_NAME = config('SHOP_NAME', default='Digital Shop')
    SHOP_SUPPORT_USERNAME = config('SHOP_SUPPORT_USERNAME', default='')

settings = Settings()
```

- [ ] **Step 2: Update env example**

Edit `.env.example` and add these lines below `ADMIN_PASSWORD`:

```text
# Used to sign web admin session cookies. Use a long random string in production.
SESSION_SECRET=replace_with_long_random_secret
SESSION_COOKIE_SECURE=false
WEB_HOST=0.0.0.0
WEB_PORT=8000
```

- [ ] **Step 3: Replace auth helper with signed cookie helpers**

Replace `app/web/auth.py` with:

```python
import hmac
import time
from hashlib import sha256

from fastapi import Request
from fastapi.responses import Response

from app.config import settings

SESSION_COOKIE_NAME = "admin_session"
SESSION_MAX_AGE_SECONDS = 86400 * 7


def _signature(payload: str) -> str:
    return hmac.new(
        settings.SESSION_SECRET.encode("utf-8"),
        payload.encode("utf-8"),
        sha256,
    ).hexdigest()


def create_session_token() -> str:
    issued_at = str(int(time.time()))
    signature = _signature(issued_at)
    return f"{issued_at}.{signature}"


def is_authenticated(request: Request) -> bool:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token or "." not in token:
        return False

    issued_at, received_signature = token.split(".", 1)
    if not issued_at.isdigit():
        return False

    expected_signature = _signature(issued_at)
    if not hmac.compare_digest(received_signature, expected_signature):
        return False

    age = int(time.time()) - int(issued_at)
    return 0 <= age <= SESSION_MAX_AGE_SECONDS


def set_admin_session(response: Response) -> None:
    response.set_cookie(
        SESSION_COOKIE_NAME,
        create_session_token(),
        httponly=True,
        max_age=SESSION_MAX_AGE_SECONDS,
        samesite="lax",
        secure=settings.SESSION_COOKIE_SECURE,
    )


def clear_admin_session(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE_NAME)
```

- [ ] **Step 4: Run compile check**

Run:

```bash
python -m compileall app/config.py app/web/auth.py
```

Expected: command exits with code `0` and no syntax errors.

---

### Task 2: Wire signed auth into web routes

**Files:**
- Modify: `app/web/main.py`

- [ ] **Step 1: Update imports**

In `app/web/main.py`, change auth import from:

```python
from app.web.auth import is_authenticated
```

to:

```python
from app.web.auth import clear_admin_session, is_authenticated, set_admin_session
```

- [ ] **Step 2: Update login cookie write**

In `post_login`, replace:

```python
response.set_cookie("admin_session", settings.ADMIN_PASSWORD, httponly=True, max_age=86400 * 7)
```

with:

```python
set_admin_session(response)
```

- [ ] **Step 3: Update logout cookie clear**

In `logout`, replace:

```python
response.delete_cookie("admin_session")
```

with:

```python
clear_admin_session(response)
```

- [ ] **Step 4: Run compile check**

Run:

```bash
python -m compileall app/web/main.py
```

Expected: command exits with code `0`.

---

### Task 3: Safe digital goods delivery service

**Files:**
- Modify: `app/services/delivery_service.py`

- [ ] **Step 1: Replace delivery service with safe text digital goods delivery**

Replace `app/services/delivery_service.py` with:

```python
from dataclasses import dataclass
from datetime import datetime

from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.models import InventoryItem, Order, OrderStatus


@dataclass(slots=True)
class DeliveryResult:
    success: bool
    message: str
    order: Order | None = None


async def _load_pending_order(session: AsyncSession, order_id: int) -> Order | None:
    result = await session.execute(
        select(Order)
        .options(selectinload(Order.product), selectinload(Order.user))
        .where(Order.id == order_id)
    )
    order = result.scalar_one_or_none()
    if not order or order.status != OrderStatus.PENDING_PAYMENT:
        return None
    return order


async def _reserve_inventory(session: AsyncSession, order: Order) -> list[InventoryItem]:
    result = await session.execute(
        select(InventoryItem)
        .where(
            InventoryItem.product_id == order.product_id,
            InventoryItem.is_sold == False,
        )
        .order_by(InventoryItem.id.asc())
        .limit(order.quantity)
    )
    return list(result.scalars().all())


def _build_delivery_text(order: Order, items: list[InventoryItem]) -> str:
    product_name = order.product.name if order.product else "sản phẩm"
    lines = [
        f"🎉 <b>Đơn hàng #{order.id} đã được duyệt!</b>",
        "",
        f"Sản phẩm: <b>{product_name}</b>",
        "Dữ liệu digital goods của bạn:",
        "",
    ]
    for index, item in enumerate(items, 1):
        lines.append(f"{index}. <code>{item.content}</code>")
    lines.extend(["", "Cảm ơn bạn đã mua sắm tại shop!"])
    return "\n".join(lines)


async def approve_and_deliver_order(session: AsyncSession, bot: Bot, order_id: int) -> DeliveryResult:
    order = await _load_pending_order(session, order_id)
    if not order:
        return DeliveryResult(False, "Đơn hàng không tồn tại hoặc đã được xử lý.")

    items = await _reserve_inventory(session, order)
    if len(items) < order.quantity:
        return DeliveryResult(
            False,
            f"Không đủ hàng trong kho. Cần {order.quantity}, còn {len(items)}.",
            order,
        )

    delivery_text = _build_delivery_text(order, items)

    try:
        await bot.send_message(chat_id=order.user_id, text=delivery_text)
    except Exception:
        await session.rollback()
        return DeliveryResult(False, "Telegram gửi hàng thất bại. Đơn vẫn chờ xử lý.", order)

    now = datetime.utcnow()
    for item in items:
        item.is_sold = True
        item.sold_at = now
        item.order_id = order.id

    order.status = OrderStatus.COMPLETED
    order.paid_at = now
    order.completed_at = now
    await session.commit()
    await session.refresh(order)
    return DeliveryResult(True, f"Đã duyệt và giao {len(items)} digital goods.", order)


async def deliver_order(session: AsyncSession, bot: Bot, order: Order) -> bool:
    result = await approve_and_deliver_order(session, bot, order.id)
    return result.success
```

- [ ] **Step 2: Run compile check**

Run:

```bash
python -m compileall app/services/delivery_service.py
```

Expected: command exits with code `0`.

---

### Task 4: Remove unsafe approve status mutation from order service callers

**Files:**
- Modify: `app/services/order_service.py`
- Modify: `app/web/main.py`
- Modify: `app/handlers/admin/orders.py`

- [ ] **Step 1: Make unsafe approve helper delegate to delivery only through explicit callers**

In `app/services/order_service.py`, replace `approve_order` with a non-mutating guard helper:

```python
async def get_pending_order(session: AsyncSession, order_id: int) -> Order | None:
    order = await session.get(Order, order_id)
    if order and order.status == OrderStatus.PENDING_PAYMENT:
        return order
    return None
```

Keep `create_order`, `update_payment_proof`, and `reject_order` unchanged.

- [ ] **Step 2: Update web approve route**

In `app/web/main.py`, replace the body of `approve_order_web` after auth check with:

```python
    if not _bot:
        return RedirectResponse(
            f"/admin/orders?status=pending_payment&msg=Bot chưa sẵn sàng, chưa thể giao đơn #{order_id}",
            status_code=302,
        )

    async with async_session() as session:
        result = await delivery_service.approve_and_deliver_order(session, _bot, order_id)

    return RedirectResponse(
        f"/admin/orders?status=pending_payment&msg={result.message}",
        status_code=302,
    )
```

- [ ] **Step 3: Update Telegram admin approve handler**

In `app/handlers/admin/orders.py`, replace approve handler session block with:

```python
    async with async_session() as session:
        result = await delivery_service.approve_and_deliver_order(session, callback.bot, order_id)

    caption = callback.message.caption or ""
    if result.success:
        await callback.message.edit_caption(caption=caption + f"\n\n✅ {result.message}")
        await callback.answer("Đã duyệt đơn hàng thành công!")
    else:
        await callback.message.edit_caption(caption=caption + f"\n\n⚠️ {result.message}")
        await callback.answer(result.message, show_alert=True)
```

Remove unused `order_service` import if no longer used by approve handler; keep it if reject handler still uses it.

- [ ] **Step 4: Run compile check**

Run:

```bash
python -m compileall app/services/order_service.py app/web/main.py app/handlers/admin/orders.py
```

Expected: command exits with code `0`.

---

### Task 5: Add internal bill image route for Telegram payment proof

**Files:**
- Modify: `app/web/main.py`
- Modify: `app/web/templates/orders.html`

- [ ] **Step 1: Add FileResponse import**

In `app/web/main.py`, change response import from:

```python
from fastapi.responses import HTMLResponse, RedirectResponse
```

to:

```python
from fastapi.responses import HTMLResponse, RedirectResponse
```

No `FileResponse` is needed because Phase 1 uses Telegram file URL redirect instead of proxying bytes.

- [ ] **Step 2: Add bill route**

Add this route before root redirect in `app/web/main.py`:

```python
@app.get("/admin/orders/{order_id}/bill")
async def order_bill(order_id: int, request: Request):
    if not is_authenticated(request):
        return _redirect_login()
    if not _bot:
        return RedirectResponse("/admin/orders?msg=Bot chưa sẵn sàng để tải bill", status_code=302)

    async with async_session() as session:
        order = await session.get(Order, order_id)
        if not order or not order.payment_proof:
            return RedirectResponse("/admin/orders?msg=Đơn không có bill", status_code=302)

    try:
        file = await _bot.get_file(order.payment_proof)
    except Exception:
        return RedirectResponse("/admin/orders?msg=Không tải được bill từ Telegram", status_code=302)

    return RedirectResponse(
        f"https://api.telegram.org/file/bot{settings.BOT_TOKEN}/{file.file_path}",
        status_code=302,
    )
```

- [ ] **Step 3: Update orders template bill link**

In `app/web/templates/orders.html`, replace:

```html
<a href="https://api.telegram.org/file/bot{{ bot_token }}/{{ order.payment_proof }}" target="_blank"
   class="inline-block text-xs text-emerald-400 hover:text-emerald-300 hover:underline">
    📷 Xem bill
</a>
```

with:

```html
<a href="/admin/orders/{{ order.id }}/bill" target="_blank"
   class="inline-block text-xs text-emerald-400 hover:text-emerald-300 hover:underline">
    📷 Xem bill
</a>
```

- [ ] **Step 4: Remove unused template variable**

In `orders_page` response context in `app/web/main.py`, remove:

```python
"bot_token": settings.BOT_TOKEN,
```

- [ ] **Step 5: Run compile check**

Run:

```bash
python -m compileall app/web/main.py
```

Expected: command exits with code `0`.

---

### Task 6: Docker and run configuration

**Files:**
- Modify: `run.py`
- Modify: `Dockerfile`
- Modify: `docker-compose.yml`

- [ ] **Step 1: Update web host/port in run.py**

In `run.py`, replace:

```python
        host="127.0.0.1",
        port=8000,
```

with:

```python
        host=settings.WEB_HOST,
        port=settings.WEB_PORT,
```

Replace log line:

```python
    logging.info("🌐 Web admin started at http://127.0.0.1:8000")
```

with:

```python
    logging.info("🌐 Web admin started at http://%s:%s", settings.WEB_HOST, settings.WEB_PORT)
```

- [ ] **Step 2: Update Dockerfile entrypoint**

In `Dockerfile`, replace:

```dockerfile
# Run the bot
CMD ["python", "app/main.py"]
```

with:

```dockerfile
# Run the Telegram bot and web admin
CMD ["python", "run.py"]
```

- [ ] **Step 3: Expose web port in docker-compose**

In `docker-compose.yml`, add ports under `bot` service:

```yaml
    ports:
      - "8000:8000"
```

The `bot` service should become:

```yaml
  bot:
    build: .
    env_file: .env
    ports:
      - "8000:8000"
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_started
    restart: always
```

- [ ] **Step 4: Run compile check**

Run:

```bash
python -m compileall run.py app/config.py
```

Expected: command exits with code `0`.

---

### Task 7: Phase 1 verification

**Files:**
- Read/verify: changed files from Tasks 1-6

- [ ] **Step 1: Compile all application code**

Run:

```bash
python -m compileall app run.py
```

Expected: command exits with code `0`.

- [ ] **Step 2: Check no password cookie pattern remains**

Search changed code for direct password cookie usage. Expected no line setting `admin_session` to `settings.ADMIN_PASSWORD`.

Use code search for:

```text
settings.ADMIN_PASSWORD
```

Expected allowed uses:

- password comparison in login route
- config definition

- [ ] **Step 3: Check approve flow no longer marks completed before delivery**

Search changed code for:

```text
order.status = OrderStatus.COMPLETED
```

Expected: only appears after Telegram `send_message` success inside `approve_and_deliver_order`.

- [ ] **Step 4: Manual smoke test if dependencies are available**

Run app:

```bash
python run.py
```

Expected:

```text
Bot started
Web admin started
```

Then verify manually:

1. Open `http://127.0.0.1:8000/login` or configured `WEB_HOST/WEB_PORT`.
2. Wrong password shows login error.
3. Correct password redirects to `/admin`.
4. Add product that represents digital goods, e.g. `Netflix 1 Month`.
5. Add inventory lines such as keys/accounts/links.
6. Create or use pending order.
7. Approve order with enough stock; Telegram user receives `InventoryItem.content` lines.
8. Approve order without enough stock; order remains `pending_payment`.
9. Open bill link for order with `payment_proof`; route redirects to Telegram file URL or shows flash error.

- [ ] **Step 5: Docker config check**

Run:

```bash
docker compose config
```

Expected: config is valid and `bot` service exposes `8000:8000`.

---

## Handoff notes

- Phase 1 treats `InventoryItem.content` as text digital goods. For files, store download links or file access instructions in `content`. Native file upload/storage should be designed later.
- If live Telegram delivery cannot be tested because token/db/redis are unavailable, complete compile checks and document blocked manual steps with exact missing dependency.
- Do not proceed to Phase 2 until approve/delivery safety is verified.
