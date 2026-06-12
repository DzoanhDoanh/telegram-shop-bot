from fastapi import FastAPI, Request, Form, Response, Header
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func, or_
import sqlalchemy as sa
from sqlalchemy.orm import selectinload
from datetime import datetime, timedelta
from html import escape
from aiogram import Bot
import time
import csv
import hmac
import hashlib
from io import StringIO
from typing import Any
from urllib.parse import quote

from app.config import settings
from app.database.session import async_session
from app.database.models import (
    User, Category, Product, Order, InventoryItem, OrderStatus,
    PaymentConfig, WalletTransaction, WalletTxStatus
)
from app.services import order_service, delivery_service, wallet_service
from app.services.order_code import get_order_code
from app.services.notification_service import (
    ANNOUNCEMENT_TYPE_NEW,
    ANNOUNCEMENT_TYPE_REMINDER,
    announce_new_product,
    announce_product,
)
from app.web.auth import (
    clear_admin_session,
    create_csrf_token,
    get_admin_actor,
    is_authenticated,
    set_admin_session,
    validate_csrf_token,
)
from app.web.audit import write_audit_event, client_ip

# ── FastAPI app & Jinja2 ──────────────────────────────────────────────────────
app = FastAPI(docs_url=None, redoc_url=None)
templates = Jinja2Templates(directory="app/web/templates")

# Shared bot instance (set once on startup)
_bot: Bot | None = None

def set_bot(bot: Bot):
    global _bot
    _bot = bot

# ── Login rate limiting ───────────────────────────────────────────────────────
_login_failures: dict[str, list[float]] = {}
_payment_unlock_failures: dict[str, list[float]] = {}

def _login_limited(ip: str) -> bool:
    now = time.time()
    window_start = now - settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS
    failures = [ts for ts in _login_failures.get(ip, []) if ts >= window_start]
    _login_failures[ip] = failures
    return len(failures) >= settings.LOGIN_RATE_LIMIT_ATTEMPTS


def _record_login_failure(ip: str) -> None:
    _login_failures.setdefault(ip, []).append(time.time())


def _payment_unlock_limited(ip: str) -> bool:
    now = time.time()
    window_start = now - settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS
    failures = [ts for ts in _payment_unlock_failures.get(ip, []) if ts >= window_start]
    _payment_unlock_failures[ip] = failures
    return len(failures) >= settings.LOGIN_RATE_LIMIT_ATTEMPTS



def _record_payment_unlock_failure(ip: str) -> None:
    _payment_unlock_failures.setdefault(ip, []).append(time.time())

# ── Helpers ───────────────────────────────────────────────────────────────────
def _redirect_login():
    return RedirectResponse("/login", status_code=302)

def _redirect_back(path: str, msg: str = ""):
    url = path if not msg else f"{path}?msg={msg}"
    return RedirectResponse(url, status_code=302)


PAYMENT_ACCESS_COOKIE = "payment_admin_access"


def _template_context(request: Request, **context):
    return {'csrf_token': create_csrf_token(request), **context}


def _payment_access_signature(value: str) -> str:
    return hmac.new(
        settings.SESSION_SECRET.encode("utf-8"),
        value.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _has_payment_access(request: Request) -> bool:
    token = request.cookies.get(PAYMENT_ACCESS_COOKIE, "")
    if "." not in token:
        return False
    issued_at, signature = token.split(".", 1)
    if not issued_at.isdigit():
        return False
    age = int(time.time()) - int(issued_at)
    if age < 0 or age > 1800:
        return False
    return hmac.compare_digest(signature, _payment_access_signature(issued_at))


def _set_payment_access(response: Response) -> None:
    issued_at = str(int(time.time()))
    response.set_cookie(
        PAYMENT_ACCESS_COOKIE,
        f"{issued_at}.{_payment_access_signature(issued_at)}",
        httponly=True,
        max_age=1800,
        samesite="lax",
        secure=settings.SESSION_COOKIE_SECURE,
    )

def _csv_response(filename: str, rows: list[dict[str, object]]) -> StreamingResponse:
    buffer = StringIO()
    fieldnames = list(rows[0].keys()) if rows else ['empty']
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows or [{'empty': ''}])
    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type='text/csv',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )

# ── Auth routes ───────────────────────────────────────────────────────────────
@app.get("/login", response_class=HTMLResponse)
async def get_login(request: Request):
    if is_authenticated(request):
        return RedirectResponse("/admin", status_code=302)
    return templates.TemplateResponse(request, "login.html", {"active_page": ""})

@app.post("/login")
async def post_login(request: Request, password: str = Form(...)):
    ip = client_ip(request)
    
    # Check rate limit
    if _login_limited(ip):
        write_audit_event(request, "login_rate_limited")
        return templates.TemplateResponse(request, "login.html", {
            "active_page": "",
            "error": "Quá nhiều lần đăng nhập thất bại. Vui lòng thử lại sau."
        })
    
    if password == settings.ADMIN_PASSWORD:
        actor = f"admin@{ip}"
        write_audit_event(request, "login_success", actor=actor)
        _login_failures.pop(ip, None)
        response = RedirectResponse("/admin", status_code=302)
        set_admin_session(response, actor)
        return response
    
    # Record failure
    write_audit_event(request, "login_failed")
    _record_login_failure(ip)
    return templates.TemplateResponse(request, "login.html", {
        "active_page": "",
        "error": "Mật khẩu không đúng. Vui lòng thử lại."
    })

@app.get("/logout")
async def logout(request: Request):
    write_audit_event(request, "logout")
    response = RedirectResponse("/login", status_code=302)
    clear_admin_session(response)
    return response

# ── Dashboard ─────────────────────────────────────────────────────────────────
@app.get("/admin/preflight")
async def admin_preflight(request: Request):
    if not is_authenticated(request):
        return _redirect_login()

    checks = {
        "bot_token": bool(settings.BOT_TOKEN),
        "admin_password_changed": settings.ADMIN_PASSWORD != "admin_secret",
        "session_secret_changed": settings.SESSION_SECRET != "change_me_session_secret",
        "payment_admin_pin": bool(settings.PAYMENT_ADMIN_PIN),
        "bot_ready": _bot is not None,
    }
    async with async_session() as session:
        config = await wallet_service.get_active_payment_config(session)
        checks.update({
            "payment_account_configured": bool(config and config.account_no and config.bank_name),
            "webhook_provider_configured": bool(config and config.webhook_provider),
            "webhook_secret_configured": bool((config and config.webhook_secret) or settings.BANK_WEBHOOK_SECRET),
        })
    return checks


@app.get("/health")
async def health_check():
    health = {"status": "ok", "database": False, "redis": False, "bot_ready": _bot is not None}
    try:
        async with async_session() as session:
            await session.execute(select(1))
        health["database"] = True
    except Exception:
        health["status"] = "degraded"

    try:
        import redis.asyncio as redis
        client = redis.from_url(settings.REDIS_URL)
        await client.ping()
        await client.aclose()
        health["redis"] = True
    except Exception:
        health["status"] = "degraded"

    if not all([health["database"], health["redis"], health["bot_ready"]]):
        health["status"] = "degraded"
    return health


@app.get("/admin", response_class=HTMLResponse)
async def dashboard(request: Request):
    if not is_authenticated(request):
        return _redirect_login()

    async with async_session() as session:
        total_orders = await session.scalar(select(func.count(Order.id))) or 0
        completed_orders = await session.scalar(
            select(func.count(Order.id)).where(Order.status == OrderStatus.COMPLETED)
        ) or 0
        revenue = await session.scalar(
            select(func.sum(Order.total_amount)).where(Order.status == OrderStatus.COMPLETED)
        ) or 0
        pending_orders = await session.scalar(
            select(func.count(Order.id)).where(Order.status == OrderStatus.PENDING_PAYMENT)
        ) or 0
        total_users = await session.scalar(select(func.count(User.id))) or 0

        pending_deposits = await session.scalar(
            select(func.count(WalletTransaction.id)).where(WalletTransaction.status == WalletTxStatus.PENDING)
        ) or 0
        review_required = await session.scalar(
            select(func.count(WalletTransaction.id)).where(WalletTransaction.status == WalletTxStatus.REVIEW_REQUIRED)
        ) or 0
        underpaid_deposits = await session.scalar(
            select(func.count(WalletTransaction.id)).where(WalletTransaction.status == WalletTxStatus.UNDERPAID)
        ) or 0
        late_paid_deposits = await session.scalar(
            select(func.count(WalletTransaction.id)).where(WalletTransaction.status == WalletTxStatus.LATE_PAID)
        ) or 0

        low_stock_result = await session.execute(
            select(
                Product.id,
                Product.name,
                func.count(InventoryItem.id).label("stock"),
            )
            .outerjoin(
                InventoryItem,
                (InventoryItem.product_id == Product.id) & (InventoryItem.is_sold == False),
            )
            .where(Product.is_active == True)
            .group_by(Product.id, Product.name)
            .having(func.count(InventoryItem.id) < 5)
            .order_by(func.count(InventoryItem.id).asc(), Product.name.asc())
            .limit(6)
        )
        low_stock_products = [
            {"id": product_id, "name": name, "stock": stock}
            for product_id, name, stock in low_stock_result.all()
        ]

        # Recent 8 orders
        result = await session.execute(
            select(Order)
            .options(selectinload(Order.product), selectinload(Order.user))
            .order_by(Order.created_at.desc())
            .limit(8)
        )
        recent_orders = result.scalars().all()

        # Revenue chart — last 7 days
        chart_labels = []
        chart_data = []
        for i in range(6, -1, -1):
            day = datetime.utcnow().date() - timedelta(days=i)
            chart_labels.append(day.strftime("%d/%m"))
            day_start = datetime.combine(day, datetime.min.time())
            day_end = datetime.combine(day, datetime.max.time())
            day_revenue = await session.scalar(
                select(func.sum(Order.total_amount)).where(
                    Order.status == OrderStatus.COMPLETED,
                    Order.completed_at >= day_start,
                    Order.completed_at <= day_end
                )
            ) or 0
            chart_data.append(float(day_revenue))

    return templates.TemplateResponse(request, "dashboard.html", _template_context(
        request,
        active_page="dashboard",
        stats={
            "revenue": revenue,
            "total_orders": total_orders,
            "completed_orders": completed_orders,
            "pending_orders": pending_orders,
            "total_users": total_users,
            "pending_deposits": pending_deposits,
            "review_required": review_required,
            "underpaid_deposits": underpaid_deposits,
            "late_paid_deposits": late_paid_deposits,
        },
        recent_orders=recent_orders,
        low_stock_products=low_stock_products,
        chart_labels=chart_labels,
        chart_data=chart_data,
    ))

# ── Orders ────────────────────────────────────────────────────────────────────
@app.get("/admin/orders", response_class=HTMLResponse)
async def orders_page(
    request: Request,
    status: str = "all",
    msg: str = "",
    q: str = "",
    product_id: str = "",
    date_from: str = "",
    date_to: str = "",
):
    if not is_authenticated(request):
        return _redirect_login()

    try:
        selected_product_id = int(product_id) if product_id else None
    except ValueError:
        selected_product_id = None

    async with async_session() as session:
        order_query = select(Order).options(
            selectinload(Order.product), selectinload(Order.user)
        ).order_by(Order.created_at.desc())

        if status != "all":
            status_map = {
                "pending_payment": OrderStatus.PENDING_PAYMENT,
                "completed": OrderStatus.COMPLETED,
                "cancelled": OrderStatus.CANCELLED,
            }
            if status in status_map:
                order_query = order_query.where(Order.status == status_map[status])

        if q:
            q_norm = q.strip()
            if q_norm:
                order_query = order_query.where(
                    or_(
                        Order.order_code.ilike(f"%{q_norm}%"),
                        func.cast(Order.id, sa.String).ilike(f"%{q_norm}%"),
                        func.cast(Order.user_id, sa.String).ilike(f"%{q_norm}%"),
                    )
                )
        if selected_product_id:
            order_query = order_query.where(Order.product_id == selected_product_id)
        if date_from:
            try:
                start = datetime.strptime(date_from, "%Y-%m-%d")
                order_query = order_query.where(Order.created_at >= start)
            except ValueError:
                pass
        if date_to:
            try:
                end = datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1)
                order_query = order_query.where(Order.created_at < end)
            except ValueError:
                pass

        products_result = await session.execute(
            select(Product).where(Product.is_active == True).order_by(Product.name.asc())
        )
        products = products_result.scalars().all()

        result = await session.execute(order_query)
        orders = result.scalars().all()
        for order in orders:
            order.display_code = get_order_code(order)

    return templates.TemplateResponse(request, "orders.html", _template_context(
        request,
        active_page="orders",
        orders=orders,
        products=products,
        current_status=status,
        q=q,
        product_id=selected_product_id,
        date_from=date_from,
        date_to=date_to,
        msg=msg,
    ))

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

@app.post("/admin/orders/{order_id}/approve")
async def approve_order_web(order_id: int, request: Request, csrf_token: str = Form(...)):
    if not is_authenticated(request):
        return _redirect_login()
    if not validate_csrf_token(request, csrf_token):
        return RedirectResponse('/login', status_code=302)

    if not _bot:
        return RedirectResponse(
            f"/admin/orders?status=pending_payment&msg=Bot chưa sẵn sàng, chưa thể giao đơn #{order_id}",
            status_code=302,
        )

    async with async_session() as session:
        result = await delivery_service.approve_and_deliver_order(session, _bot, order_id)

    write_audit_event(request, "order_approve", order_id=order_id)
    return RedirectResponse(
        f"/admin/orders?status=pending_payment&msg={result.message}",
        status_code=302,
    )

@app.post("/admin/orders/{order_id}/reject")
async def reject_order_web(
    order_id: int,
    request: Request,
    reason: str = Form(""),
    csrf_token: str = Form(...),
):
    if not is_authenticated(request):
        return _redirect_login()
    if not validate_csrf_token(request, csrf_token):
        return RedirectResponse('/login', status_code=302)

    async with async_session() as session:
        order = await order_service.reject_order(session, order_id)
        if order and _bot:
            reject_reason = escape(reason.strip() or 'Thanh toán chưa hợp lệ hoặc chưa xác minh được.')
            order_code = escape(get_order_code(order))
            try:
                await _bot.send_message(
                    chat_id=order.user_id,
                    text=(
                        f"❌ <b>Đơn hàng {order_code} đã bị từ chối.</b>\n\n"
                        f"Lý do: {reject_reason}\n\n"
                        "Vui lòng liên hệ hỗ trợ nếu bạn có thắc mắc."
                    )
                )
            except Exception:
                pass

    write_audit_event(request, "order_reject", order_id=order_id)
    order_label = order.order_code if order else f"DH{order_id:06d}"
    return RedirectResponse(f"/admin/orders?status=pending_payment&msg=Đã từ chối đơn {order_label}", status_code=302)

# ── Products ──────────────────────────────────────────────────────────────────
@app.get("/admin/products", response_class=HTMLResponse)
async def products_page(request: Request, msg: str = "", q: str = "", category_id: str = ""):
    if not is_authenticated(request):
        return _redirect_login()

    try:
        selected_category_id = int(category_id) if category_id else None
    except ValueError:
        selected_category_id = None

    async with async_session() as session:
        categories_result = await session.execute(
            select(Category).where(Category.is_active == True).order_by(Category.name.asc())
        )
        categories = categories_result.scalars().all()

        product_query = (
            select(Product)
            .options(selectinload(Product.category))
            .where(Product.is_active == True)
            .order_by(Product.created_at.desc())
        )
        if q:
            product_query = product_query.where(Product.name.ilike(f"%{q}%"))
        if selected_category_id:
            product_query = product_query.where(Product.category_id == selected_category_id)

        result = await session.execute(product_query)
        raw_products = result.scalars().all()

        products = []
        for p in raw_products:
            stock = await session.scalar(
                select(func.count(InventoryItem.id)).where(
                    InventoryItem.product_id == p.id, InventoryItem.is_sold == False
                )
            ) or 0
            products.append({"id": p.id, "category_id": p.category_id, "name": p.name, "price": p.price,
                             "description": p.description, "category": p.category, "stock": stock,
                             "delivery_mode": p.delivery_mode, "fixed_delivery_content": p.fixed_delivery_content,
                             "allow_quantity_selection": p.allow_quantity_selection, "min_quantity": p.min_quantity, "max_quantity": p.max_quantity})

    return templates.TemplateResponse(request, "products.html", _template_context(
        request,
        active_page="products",
        products=products,
        categories=categories,
        q=q,
        category_id=selected_category_id,
        msg=msg,
    ))

@app.post("/admin/products/add")
async def add_product_web(
    request: Request,
    name: str = Form(...),
    price: float = Form(...),
    description: str = Form(""),
    category_id: int | None = Form(None),
    new_category: str = Form(""),
    delivery_mode: str = Form("inventory"),
    fixed_delivery_content: str = Form(""),
    allow_quantity_selection: bool = Form(False),
    min_quantity: int = Form(1),
    max_quantity: int = Form(1),
    csrf_token: str = Form(...),
):
    if not is_authenticated(request):
        return _redirect_login()
    if not validate_csrf_token(request, csrf_token):
        return RedirectResponse('/login', status_code=302)

    normalized_delivery_mode = delivery_mode if delivery_mode in {"inventory", "fixed_content"} else "inventory"
    normalized_fixed_delivery_content = fixed_delivery_content.strip() or None
    quantity_enabled = bool(allow_quantity_selection)
    min_quantity = max(1, int(min_quantity or 1))
    max_quantity = max(min_quantity, int(max_quantity or 1))
    if normalized_delivery_mode == "fixed_content":
        quantity_enabled = False
        min_quantity = 1
        max_quantity = 1
    elif not quantity_enabled:
        min_quantity = 1
        max_quantity = 1

    async with async_session() as session:
        cat = None
        if category_id:
            cat = await session.scalar(
                select(Category).where(Category.id == category_id, Category.is_active == True)
            )
        if not cat and new_category.strip():
            cat = Category(name=new_category.strip(), emoji="📦")
            session.add(cat)
            await session.flush()
        if not cat:
            cat = await session.scalar(select(Category).where(Category.is_active == True).limit(1))
        if not cat:
            cat = Category(name="General", emoji="📦")
            session.add(cat)
            await session.flush()

        product = Product(
            category_id=cat.id,
            name=name.strip(),
            price=price,
            description=description.strip() or None,
            delivery_mode=normalized_delivery_mode,
            fixed_delivery_content=normalized_fixed_delivery_content,
            allow_quantity_selection=quantity_enabled,
            min_quantity=min_quantity,
            max_quantity=max_quantity,
        )
        session.add(product)
        await session.commit()
        await session.refresh(product)
        product_id = product.id

    write_audit_event(request, "product_add", product_id=product_id, name=name, announcement_sent=0)
    msg = f"Đã thêm sản phẩm '{name}' thành công. Thông báo sẽ chỉ được gửi khi sản phẩm có hàng trong kho."
    return RedirectResponse(f"/admin/products?msg={quote(msg)}", status_code=302)

@app.post("/admin/products/{product_id}/edit")
async def edit_product_web(
    product_id: int,
    request: Request,
    name: str = Form(...),
    price: float = Form(...),
    description: str = Form(""),
    category_id: int | None = Form(None),
    new_category: str = Form(""),
    delivery_mode: str = Form("inventory"),
    fixed_delivery_content: str = Form(""),
    allow_quantity_selection: bool = Form(False),
    min_quantity: int = Form(1),
    max_quantity: int = Form(1),
    csrf_token: str = Form(...),
):
    if not is_authenticated(request):
        return _redirect_login()
    if not validate_csrf_token(request, csrf_token):
        return RedirectResponse('/login', status_code=302)

    normalized_delivery_mode = delivery_mode if delivery_mode in {"inventory", "fixed_content"} else "inventory"
    normalized_fixed_delivery_content = fixed_delivery_content.strip() or None
    quantity_enabled = bool(allow_quantity_selection)
    min_quantity = max(1, int(min_quantity or 1))
    max_quantity = max(min_quantity, int(max_quantity or 1))
    if normalized_delivery_mode == "fixed_content":
        quantity_enabled = False
        min_quantity = 1
        max_quantity = 1
    elif not quantity_enabled:
        min_quantity = 1
        max_quantity = 1

    async with async_session() as session:
        product = await session.get(Product, product_id)
        if not product or not product.is_active:
            return RedirectResponse("/admin/products?msg=Sản phẩm không tồn tại", status_code=302)

        cat = None
        if category_id:
            cat = await session.scalar(
                select(Category).where(Category.id == category_id, Category.is_active == True)
            )
        if not cat and new_category.strip():
            cat = Category(name=new_category.strip(), emoji="📦")
            session.add(cat)
            await session.flush()
        if not cat:
            cat = await session.scalar(
                select(Category).where(Category.id == product.category_id, Category.is_active == True)
            )
        if not cat:
            cat = await session.scalar(select(Category).where(Category.is_active == True).limit(1))
        if not cat:
            cat = Category(name="General", emoji="📦")
            session.add(cat)
            await session.flush()

        product.name = name.strip()
        product.price = price
        product.description = description.strip() or None
        product.category_id = cat.id
        product.delivery_mode = normalized_delivery_mode
        product.fixed_delivery_content = normalized_fixed_delivery_content
        product.allow_quantity_selection = quantity_enabled
        product.min_quantity = min_quantity
        product.max_quantity = max_quantity
        await session.commit()

    write_audit_event(request, "product_edit", product_id=product_id, name=name)
    return RedirectResponse(f"/admin/products?msg=Đã cập nhật sản phẩm '{name}'", status_code=302)

@app.post("/admin/products/{product_id}/disable")
async def disable_product_web(product_id: int, request: Request, csrf_token: str = Form(...)):
    if not is_authenticated(request):
        return _redirect_login()
    if not validate_csrf_token(request, csrf_token):
        return RedirectResponse('/login', status_code=302)

    async with async_session() as session:
        product = await session.get(Product, product_id)
        if not product or not product.is_active:
            return RedirectResponse("/admin/products?msg=Sản phẩm không tồn tại", status_code=302)
        product_name = product.name
        product.is_active = False
        await session.commit()

    write_audit_event(request, "product_disable", product_id=product_id, name=product_name)
    return RedirectResponse(f"/admin/products?msg=Đã xóa sản phẩm #{product_id} khỏi shop", status_code=302)


@app.post("/admin/products/{product_id}/announce")
async def announce_product_web(
    product_id: int,
    request: Request,
    kind: str = Form(...),
    csrf_token: str = Form(...),
):
    if not is_authenticated(request):
        return _redirect_login()
    if not validate_csrf_token(request, csrf_token):
        return RedirectResponse('/login', status_code=302)

    if kind not in {ANNOUNCEMENT_TYPE_NEW, ANNOUNCEMENT_TYPE_REMINDER}:
        return RedirectResponse(f"/admin/products?msg={quote('Loại thông báo không hợp lệ')}", status_code=302)

    async with async_session() as session:
        product = await session.get(Product, product_id, options=[selectinload(Product.category)])
        if not product or not product.is_active:
            return RedirectResponse(f"/admin/products?msg={quote('Sản phẩm không tồn tại hoặc đã ngừng bán')}", status_code=302)

        stock = await session.scalar(
            select(func.count(InventoryItem.id)).where(
                InventoryItem.product_id == product_id,
                InventoryItem.is_sold == False,
            )
        ) or 0
        if product.delivery_mode != "fixed_content" and stock <= 0:
            msg = f"Không thể gửi thông báo cho sản phẩm '{product.name}' vì hiện đang hết hàng."
            return RedirectResponse(f"/admin/products?msg={quote(msg)}", status_code=302)

        sent = 0
        try:
            sent = await announce_product(_bot, session, product_id, kind)
        except Exception:
            sent = 0

    kind_label = "sản phẩm mới" if kind == ANNOUNCEMENT_TYPE_NEW else "nhắc lại sản phẩm cũ"
    write_audit_event(request, "product_announce", product_id=product_id, kind=kind, sent=sent)
    msg = f"Đã gửi thông báo {kind_label} cho sản phẩm #{product_id} tới {sent} người dùng."
    return RedirectResponse(f"/admin/products?msg={quote(msg)}", status_code=302)

# ── Categories ────────────────────────────────────────────────────────────────
@app.get("/admin/categories", response_class=HTMLResponse)
async def categories_page(request: Request, msg: str = ""):
    if not is_authenticated(request):
        return _redirect_login()

    async with async_session() as session:
        result = await session.execute(
            select(Category, func.count(Product.id).label("product_count"))
            .outerjoin(
                Product,
                (Product.category_id == Category.id) & (Product.is_active == True),
            )
            .where(Category.is_active == True)
            .group_by(Category.id)
            .order_by(Category.name.asc())
        )
        categories = [
            {
                "id": category.id,
                "name": category.name,
                "description": category.description,
                "emoji": category.emoji,
                "product_count": product_count,
            }
            for category, product_count in result.all()
        ]

    return templates.TemplateResponse(request, "categories.html", _template_context(
        request,
        active_page="categories",
        categories=categories,
        msg=msg,
    ))


@app.post("/admin/categories/add")
async def add_category_web(
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    emoji: str = Form("📦"),
    csrf_token: str = Form(...),
):
    if not is_authenticated(request):
        return _redirect_login()
    if not validate_csrf_token(request, csrf_token):
        return RedirectResponse('/login', status_code=302)

    category_name = name.strip()
    if not category_name:
        return RedirectResponse("/admin/categories?msg=Tên danh mục không được để trống", status_code=302)

    async with async_session() as session:
        existing = await session.scalar(
            select(Category).where(
                func.lower(Category.name) == category_name.lower(),
                Category.is_active == True,
            )
        )
        if existing:
            return RedirectResponse("/admin/categories?msg=Danh mục này đã tồn tại", status_code=302)

        category = Category(
            name=category_name,
            description=description.strip() or None,
            emoji=(emoji.strip() or "📦")[:10],
            is_active=True,
        )
        session.add(category)
        await session.commit()
        await session.refresh(category)

    write_audit_event(request, "category_add", category_id=category.id, name=category_name)
    return RedirectResponse(f"/admin/categories?msg=Đã tạo danh mục '{category_name}'", status_code=302)


@app.post("/admin/categories/{category_id}/edit")
async def edit_category_web(
    category_id: int,
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    emoji: str = Form("📦"),
    csrf_token: str = Form(...),
):
    if not is_authenticated(request):
        return _redirect_login()
    if not validate_csrf_token(request, csrf_token):
        return RedirectResponse('/login', status_code=302)

    category_name = name.strip()
    if not category_name:
        return RedirectResponse("/admin/categories?msg=Tên danh mục không được để trống", status_code=302)

    async with async_session() as session:
        category = await session.scalar(
            select(Category).where(Category.id == category_id, Category.is_active == True)
        )
        if not category:
            return RedirectResponse("/admin/categories?msg=Danh mục không tồn tại", status_code=302)

        duplicate = await session.scalar(
            select(Category).where(
                Category.id != category_id,
                func.lower(Category.name) == category_name.lower(),
                Category.is_active == True,
            )
        )
        if duplicate:
            return RedirectResponse("/admin/categories?msg=Danh mục này đã tồn tại", status_code=302)

        category.name = category_name
        category.description = description.strip() or None
        category.emoji = (emoji.strip() or "📦")[:10]
        await session.commit()

    write_audit_event(request, "category_edit", category_id=category_id, name=category_name)
    return RedirectResponse(f"/admin/categories?msg=Đã cập nhật danh mục '{category_name}'", status_code=302)


@app.post("/admin/categories/{category_id}/delete")
async def delete_category_web(category_id: int, request: Request, csrf_token: str = Form(...)):
    if not is_authenticated(request):
        return _redirect_login()
    if not validate_csrf_token(request, csrf_token):
        return RedirectResponse('/login', status_code=302)

    async with async_session() as session:
        category = await session.scalar(
            select(Category).where(Category.id == category_id, Category.is_active == True)
        )
        if not category:
            return RedirectResponse("/admin/categories?msg=Danh mục không tồn tại", status_code=302)

        active_products = await session.scalar(
            select(func.count(Product.id)).where(
                Product.category_id == category_id,
                Product.is_active == True,
            )
        ) or 0
        if active_products > 0:
            return RedirectResponse(
                "/admin/categories?msg=Không thể xóa danh mục đang có sản phẩm. Hãy chuyển hoặc xóa sản phẩm trước.",
                status_code=302,
            )

        category_name = category.name
        category.is_active = False
        await session.commit()

    write_audit_event(request, "category_delete", category_id=category_id, name=category_name)
    return RedirectResponse(f"/admin/categories?msg=Đã xóa danh mục '{category_name}'", status_code=302)


# ── Inventory ─────────────────────────────────────────────────────────────────
@app.get("/admin/inventory", response_class=HTMLResponse)
async def inventory_page(request: Request, product_id: int = None, msg: str = ""):
    if not is_authenticated(request):
        return _redirect_login()

    async with async_session() as session:
        result = await session.execute(select(Product).where(Product.is_active == True))
        raw_products = result.scalars().all()

        products = []
        fixed_content_products = []
        for p in raw_products:
            stock = await session.scalar(
                select(func.count(InventoryItem.id)).where(
                    InventoryItem.product_id == p.id, InventoryItem.is_sold == False
                )
            ) or 0
            product_info = {"id": p.id, "name": p.name, "price": p.price, "stock": stock, "delivery_mode": p.delivery_mode}
            if p.delivery_mode == "fixed_content":
                fixed_content_products.append(product_info)
            else:
                products.append(product_info)

    return templates.TemplateResponse(request, "inventory.html", _template_context(
        request,
        active_page="inventory",
        products=products,
        fixed_content_products=fixed_content_products,
        selected_product_id=product_id,
        msg=msg,
    ))

@app.post("/admin/inventory/add")
async def add_inventory_web(
    request: Request,
    product_id: int = Form(...),
    keys: str = Form(...),
    csrf_token: str = Form(...),
    dry_run: str = Form("0"),
):
    if not is_authenticated(request):
        return _redirect_login()
    if not validate_csrf_token(request, csrf_token):
        return RedirectResponse('/login', status_code=302)

    raw_lines = keys.splitlines()
    blank_count = sum(1 for line in raw_lines if not line.strip())
    seen = set()
    items = []
    request_duplicate_count = 0
    for line in raw_lines:
        item = line.strip()
        if not item:
            continue
        if item in seen:
            request_duplicate_count += 1
            continue
        seen.add(item)
        items.append(item)

    if not items:
        return RedirectResponse("/admin/inventory?msg=Không có dữ liệu sản phẩm hợp lệ nào", status_code=302)

    existing = set()
    new_items = []
    product_name = ""
    announcement_sent = 0
    import_batch_id = f"batch-{int(time.time())}-{product_id}"
    async with async_session() as session:
        product = await session.get(Product, product_id)
        if not product:
            return RedirectResponse("/admin/inventory?msg=Sản phẩm không tồn tại", status_code=302)
        if product.delivery_mode == "fixed_content":
            return RedirectResponse(
                f"/admin/inventory?msg={quote('Sản phẩm này dùng nội dung cố định, không nhập kho theo từng dòng.')}",
                status_code=302,
            )
        product_name = product.name
        stock_before = await session.scalar(
            select(func.count(InventoryItem.id)).where(
                InventoryItem.product_id == product_id,
                InventoryItem.is_sold == False,
            )
        ) or 0

        result = await session.execute(
            select(InventoryItem.content).where(
                InventoryItem.product_id == product_id,
                InventoryItem.content.in_(items),
            )
        )
        existing = set(result.scalars().all())
        new_items = [item for item in items if item not in existing]

        if dry_run == "1":
            msg = f"Preview nhập kho '{product_name}': thêm mới {len(new_items)}, trùng {request_duplicate_count + len(existing)}, dòng trống {blank_count}. Chưa ghi vào DB."
            write_audit_event(request, "inventory_import_preview", product_id=product_id, count=len(new_items), duplicate_count=request_duplicate_count + len(existing), blank_count=blank_count)
            return RedirectResponse(
                f"/admin/inventory?product_id={product_id}&msg={quote(msg)}",
                status_code=302,
            )

        for item in new_items:
            session.add(InventoryItem(product_id=product_id, content=item, order_id=None))
        await session.commit()

        if stock_before == 0 and new_items:
            try:
                announcement_sent = await announce_new_product(_bot, session, product_id)
            except Exception:
                announcement_sent = 0

    write_audit_event(request, "inventory_import", product_id=product_id, count=len(new_items), announcement_sent=announcement_sent, import_batch_id=import_batch_id)
    duplicate_count = request_duplicate_count + len(existing)
    msg = f"✅ Đã thêm {len(new_items)} mục dữ liệu sản phẩm vào kho '{product_name}'. Trùng: {duplicate_count}. Dòng trống: {blank_count}."
    if announcement_sent:
        msg = f"{msg} Đã gửi thông báo tới {announcement_sent} người dùng."
    return RedirectResponse(
        f"/admin/inventory?product_id={product_id}&msg={quote(msg)}",
        status_code=302
    )

# ── Export routes ─────────────────────────────────────────────────────────────
@app.get("/admin/export/orders.csv")
async def export_orders_csv(request: Request):
    if not is_authenticated(request):
        return _redirect_login()

    async with async_session() as session:
        result = await session.execute(
            select(Order)
            .options(selectinload(Order.product), selectinload(Order.user))
            .order_by(Order.created_at.desc())
        )
        orders = result.scalars().all()

        rows = []
        for order in orders:
            rows.append({
                'id': order.id,
                'user_id': order.user_id,
                'product_name': order.product.name if order.product else '',
                'status': order.status.value,
                'quantity': order.quantity,
                'total_amount': float(order.total_amount),
                'created_at': order.created_at.isoformat() if order.created_at else '',
                'completed_at': order.completed_at.isoformat() if order.completed_at else '',
            })

    write_audit_event(request, "export_orders_csv", count=len(rows))
    return _csv_response('orders.csv', rows)

@app.get("/admin/export/products.csv")
async def export_products_csv(request: Request):
    if not is_authenticated(request):
        return _redirect_login()

    async with async_session() as session:
        result = await session.execute(
            select(Product)
            .options(selectinload(Product.category))
            .where(Product.is_active == True)
            .order_by(Product.created_at.desc())
        )
        products = result.scalars().all()

        rows = []
        for product in products:
            stock = await session.scalar(
                select(func.count(InventoryItem.id)).where(
                    InventoryItem.product_id == product.id,
                    InventoryItem.is_sold == False
                )
            ) or 0

            rows.append({
                'id': product.id,
                'category_name': product.category.name if product.category else '',
                'name': product.name,
                'price': float(product.price),
                'stock': stock,
                'is_active': product.is_active,
                'created_at': product.created_at.isoformat() if product.created_at else '',
            })

    write_audit_event(request, "export_products_csv", count=len(rows))
    return _csv_response('products.csv', rows)

@app.get("/admin/export/inventory.csv")
async def export_inventory_csv(request: Request):
    if not is_authenticated(request):
        return _redirect_login()

    async with async_session() as session:
        result = await session.execute(
            select(Product).where(Product.is_active == True).order_by(Product.name.asc())
        )
        products = result.scalars().all()

        rows = []
        for product in products:
            available = await session.scalar(
                select(func.count(InventoryItem.id)).where(
                    InventoryItem.product_id == product.id,
                    InventoryItem.is_sold == False
                )
            ) or 0

            sold = await session.scalar(
                select(func.count(InventoryItem.id)).where(
                    InventoryItem.product_id == product.id,
                    InventoryItem.is_sold == True
                )
            ) or 0

            rows.append({
                'product_id': product.id,
                'product_name': product.name,
                'available': available,
                'sold': sold,
                'total': available + sold,
            })

    write_audit_event(request, "export_inventory_csv", count=len(rows))
    return _csv_response('inventory.csv', rows)

# ── Bank webhook ──────────────────────────────────────────────────────────────
@app.post("/webhooks/bank/{provider}")
async def bank_webhook(
    provider: str,
    request: Request,
    x_webhook_secret: str = Header("", alias="X-Webhook-Secret"),
    x_sepay_signature: str = Header("", alias="X-SePay-Signature"),
    x_sepay_timestamp: str = Header("", alias="X-SePay-Timestamp"),
):
    raw_body = await request.body()
    payload: dict[str, Any] = await request.json()

    async with async_session() as session:
        config = await wallet_service.get_active_payment_config(session)
        configured_provider = ((config.webhook_provider if config else None) or provider or "").strip().lower()
        expected_secret = (config.webhook_secret if config else None) or settings.BANK_WEBHOOK_SECRET

        if configured_provider and provider.strip().lower() != configured_provider:
            write_audit_event(request, "bank_webhook_provider_mismatch", provider=provider, configured_provider=configured_provider)
            return Response("Provider mismatch", status_code=400)

        if expected_secret:
            if configured_provider == "sepay":
                try:
                    timestamp_value = int((x_sepay_timestamp or "").strip())
                except ValueError:
                    write_audit_event(request, "bank_webhook_forbidden", provider=provider, reason="invalid_timestamp")
                    return Response("Forbidden", status_code=403)

                now_ts = int(datetime.utcnow().timestamp())
                if abs(now_ts - timestamp_value) > settings.WEBHOOK_MAX_AGE_SECONDS:
                    write_audit_event(request, "bank_webhook_forbidden", provider=provider, reason="stale_timestamp", timestamp=timestamp_value)
                    return Response("Forbidden", status_code=403)

                hmac_message = f"{x_sepay_timestamp}.".encode("utf-8") + raw_body
                expected_hmac = "sha256=" + hmac.new(
                    expected_secret.encode("utf-8"),
                    hmac_message,
                    hashlib.sha256,
                ).hexdigest()
                has_valid_hmac = bool(x_sepay_signature and x_sepay_timestamp) and hmac.compare_digest(
                    x_sepay_signature.strip().lower(),
                    expected_hmac,
                )
                if not has_valid_hmac:
                    write_audit_event(request, "bank_webhook_forbidden", provider=provider, reason="invalid_hmac")
                    return Response("Forbidden", status_code=403)
            else:
                has_valid_secret_header = bool(x_webhook_secret) and hmac.compare_digest(
                    x_webhook_secret,
                    expected_secret,
                )
                if not has_valid_secret_header:
                    write_audit_event(request, "bank_webhook_forbidden", provider=provider, reason="invalid_secret_header")
                    return Response("Forbidden", status_code=403)

        result = await wallet_service.process_bank_webhook(session, provider, payload, _bot)

    write_audit_event(
        request,
        "bank_webhook_received",
        provider=provider,
        success=result.success,
        message=result.message,
    )
    return {
        "success": True,
        "processed": result.success,
        "message": result.message,
        "transaction_id": result.transaction.id if result.transaction else None,
    }


# ── Wallet & payment admin ────────────────────────────────────────────────────
@app.get("/admin/payments/unlock", response_class=HTMLResponse)
async def payments_unlock_page(request: Request, error: str = ""):
    if not is_authenticated(request):
        return _redirect_login()
    return templates.TemplateResponse(request, "payments_unlock.html", _template_context(
        request,
        active_page="payments",
        error=error,
    ))


@app.post("/admin/payments/unlock")
async def payments_unlock_web(request: Request, csrf_token: str = Form(...), pin: str = Form(...)):
    if not is_authenticated(request):
        return _redirect_login()
    if not validate_csrf_token(request, csrf_token):
        return Response("CSRF token không hợp lệ", status_code=403)

    ip = client_ip(request)
    if _payment_unlock_limited(ip):
        write_audit_event(request, "payment_unlock_rate_limited")
        return RedirectResponse("/admin/payments/unlock?error=Bạn nhập sai quá nhiều lần, vui lòng thử lại sau", status_code=302)

    expected_pin = settings.PAYMENT_ADMIN_PIN
    if not expected_pin or not hmac.compare_digest(pin, expected_pin):
        _record_payment_unlock_failure(ip)
        write_audit_event(request, "payment_unlock_failed")
        return RedirectResponse("/admin/payments/unlock?error=Mã bảo vệ không đúng", status_code=302)

    write_audit_event(request, "payment_unlock_success")
    response = RedirectResponse("/admin/payments", status_code=302)
    _set_payment_access(response)
    return response


@app.get("/admin/payments", response_class=HTMLResponse)
async def payments_page(request: Request, msg: str = "", status: str = "", q: str = "", page: int = 1):
    if not is_authenticated(request):
        return _redirect_login()
    if not _has_payment_access(request):
        return RedirectResponse("/admin/payments/unlock", status_code=302)

    page = max(page, 1)
    per_page = 50

    async with async_session() as session:
        config = await wallet_service.ensure_payment_config(session)
        filters = []
        if status:
            try:
                filters.append(WalletTransaction.status == WalletTxStatus(status))
            except ValueError:
                pass
        if q.strip():
            keyword = q.strip()
            search_filters = [
                WalletTransaction.reference.ilike(f"%{keyword}%"),
                WalletTransaction.normalized_reference.ilike(f"%{keyword}%"),
                WalletTransaction.provider_tx_id.ilike(f"%{keyword}%"),
                WalletTransaction.provider_event_id.ilike(f"%{keyword}%"),
                WalletTransaction.note.ilike(f"%{keyword}%"),
                WalletTransaction.admin_actor.ilike(f"%{keyword}%"),
            ]
            if keyword.isdigit():
                numeric_keyword = int(keyword)
                search_filters.append(WalletTransaction.user_id == numeric_keyword)
                if numeric_keyword <= 2_147_483_647:
                    search_filters.append(WalletTransaction.id == numeric_keyword)
            filters.append(or_(*search_filters))

        total_count = await session.scalar(
            select(func.count(WalletTransaction.id)).where(*filters)
        ) or 0
        total_pages = max((total_count + per_page - 1) // per_page, 1)
        if page > total_pages:
            page = total_pages

        query = (
            select(WalletTransaction)
            .options(selectinload(WalletTransaction.user))
            .where(*filters)
            .order_by(WalletTransaction.created_at.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
        result = await session.execute(query)
        transactions = result.scalars().all()
        review_counts = {
            "pending": await session.scalar(select(func.count(WalletTransaction.id)).where(WalletTransaction.status == WalletTxStatus.PENDING)) or 0,
            "underpaid": await session.scalar(select(func.count(WalletTransaction.id)).where(WalletTransaction.status == WalletTxStatus.UNDERPAID)) or 0,
            "review_required": await session.scalar(select(func.count(WalletTransaction.id)).where(WalletTransaction.status == WalletTxStatus.REVIEW_REQUIRED)) or 0,
            "late_paid": await session.scalar(select(func.count(WalletTransaction.id)).where(WalletTransaction.status == WalletTxStatus.LATE_PAID)) or 0,
        }

    return templates.TemplateResponse(request, "payments.html", _template_context(
        request,
        active_page="payments",
        msg=msg,
        config=config,
        transactions=transactions,
        current_status=status,
        review_counts=review_counts,
        current_query=q,
        current_page=page,
        total_pages=total_pages,
        total_count=total_count,
        per_page=per_page,
    ))


@app.post("/admin/payments/config")
async def update_payment_config_web(
    request: Request,
    csrf_token: str = Form(...),
    bank_name: str = Form(""),
    account_no: str = Form(""),
    account_name: str = Form(""),
    vietqr_bank_code: str = Form(""),
    webhook_secret: str = Form(""),
    webhook_provider: str = Form(""),
):
    if not is_authenticated(request):
        return _redirect_login()
    if not _has_payment_access(request):
        return RedirectResponse("/admin/payments/unlock", status_code=302)
    if not validate_csrf_token(request, csrf_token):
        return Response("CSRF token không hợp lệ", status_code=403)

    async with async_session() as session:
        config = await wallet_service.ensure_payment_config(session)
        config.bank_name = bank_name.strip() or None
        config.account_no = account_no.strip() or None
        config.account_name = account_name.strip() or None
        config.vietqr_bank_code = vietqr_bank_code.strip() or None
        if webhook_secret.strip():
            config.webhook_secret = webhook_secret.strip()
        config.webhook_provider = webhook_provider.strip().lower() or None
        config.is_active = True
        await session.commit()

    write_audit_event(request, "update_payment_config")
    return _redirect_back("/admin/payments", "Đã lưu cấu hình thanh toán")


@app.post("/admin/payments/wallet-transactions/{tx_id}/cancel")
async def cancel_wallet_transaction_web(
    tx_id: int,
    request: Request,
    csrf_token: str = Form(...),
    reason: str = Form("Admin hủy giao dịch pending"),
):
    if not is_authenticated(request):
        return _redirect_login()
    if not _has_payment_access(request):
        return RedirectResponse("/admin/payments/unlock", status_code=302)
    if not validate_csrf_token(request, csrf_token):
        return Response("CSRF token không hợp lệ", status_code=403)

    actor = get_admin_actor(request)
    async with async_session() as session:
        result = await wallet_service.cancel_wallet_transaction_admin(session, tx_id, actor, reason)

    write_audit_event(request, "cancel_wallet_transaction", tx_id=tx_id, actor=actor, success=result.success, reason=reason)
    return _redirect_back("/admin/payments", result.message)


@app.post("/admin/payments/wallet-adjust")
async def wallet_adjustment_web(
    request: Request,
    csrf_token: str = Form(...),
    user_id: int = Form(...),
    amount: str = Form(...),
    action: str = Form(...),
    reason: str = Form(...),
):
    if not is_authenticated(request):
        return _redirect_login()
    if not _has_payment_access(request):
        return RedirectResponse("/admin/payments/unlock", status_code=302)
    if not validate_csrf_token(request, csrf_token):
        return Response("CSRF token không hợp lệ", status_code=403)

    actor = get_admin_actor(request)
    tx_type_map = {
        "refund": wallet_service.WalletTxType.REFUND,
        "credit": wallet_service.WalletTxType.ADMIN_CREDIT,
        "debit": wallet_service.WalletTxType.ADMIN_DEBIT,
    }
    tx_type = tx_type_map.get(action)
    if not tx_type:
        return _redirect_back("/admin/payments", "Loại điều chỉnh ví không hợp lệ")

    async with async_session() as session:
        result = await wallet_service.adjust_wallet_balance(session, user_id, amount, tx_type, actor, reason)

    write_audit_event(request, "wallet_adjustment", actor=actor, user_id=user_id, amount=amount, adjustment_type=action, success=result.success, reason=reason, tx_id=result.transaction.id if result.transaction else None)
    return _redirect_back("/admin/payments", result.message)


# ── Root redirect ─────────────────────────────────────────────────────────────
@app.get("/")
async def root():
    return RedirectResponse("/admin", status_code=302)
