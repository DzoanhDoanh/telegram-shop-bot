from fastapi import FastAPI, Request, Form, Response, Header
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func, or_
from sqlalchemy.orm import selectinload
from datetime import datetime, timedelta
from aiogram import Bot
import time
import csv
import hmac
import hashlib
from io import StringIO
from typing import Any

from app.config import settings
from app.database.session import async_session
from app.database.models import (
    User, Product, Order, InventoryItem, OrderStatus,
    WalletTransaction, WalletTxStatus
)
from app.services import wallet_service, app_config_service
from app.web.auth import (
    clear_admin_session,
    create_csrf_token,
    is_authenticated,
    set_admin_session,
    validate_csrf_token,
)
from app.web.audit import write_audit_event, client_ip
from app.web.routes.settings import bind_routes as bind_settings_routes
from app.web.routes.payments import bind_routes as bind_payments_routes
from app.web.routes.users import bind_routes as bind_users_routes
from app.web.routes.orders import bind_routes as bind_orders_routes
from app.web.routes.products import bind_routes as bind_products_routes
from app.web.routes.inventory import bind_routes as bind_inventory_routes
from app.web.routes.categories import bind_routes as bind_categories_routes
from app.web.routes.exports import bind_routes as bind_export_routes
from app.web.routes.support import bind_routes as bind_support_routes
from app.web.routes.auth_pages import bind_routes as bind_auth_pages_routes
from app.web.routes.dashboard import bind_routes as bind_dashboard_routes
from app.web.routes.public_pages import bind_routes as bind_public_pages_routes
from app.web.routes.vouchers import bind_routes as bind_vouchers_routes
from app.web.routes.broadcasts import bind_routes as bind_broadcasts_routes

# ── FastAPI app & Jinja2 ──────────────────────────────────────────────────────
app = FastAPI(docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory="app/web/static"), name="static")
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


app.include_router(bind_settings_routes(
    templates=templates,
    template_context=_template_context,
    is_authenticated=is_authenticated,
    redirect_login=_redirect_login,
    redirect_back=_redirect_back,
))
app.include_router(bind_payments_routes(
    templates=templates,
    template_context=_template_context,
    is_authenticated=is_authenticated,
    redirect_login=_redirect_login,
    has_payment_access=_has_payment_access,
    set_payment_access=_set_payment_access,
    payment_unlock_limited=_payment_unlock_limited,
    record_payment_unlock_failure=_record_payment_unlock_failure,
    redirect_back=_redirect_back,
))
app.include_router(bind_users_routes(
    templates=templates,
    template_context=_template_context,
    is_authenticated=is_authenticated,
    redirect_login=_redirect_login,
    redirect_back=_redirect_back,
    has_payment_access=_has_payment_access,
))
app.include_router(bind_orders_routes(
    templates=templates,
    template_context=_template_context,
    is_authenticated=is_authenticated,
    redirect_login=_redirect_login,
    redirect_back=_redirect_back,
    has_payment_access=_has_payment_access,
    bot_getter=lambda: _bot,
))
app.include_router(bind_products_routes(
    templates=templates,
    template_context=_template_context,
    is_authenticated=is_authenticated,
    redirect_login=_redirect_login,
    bot_getter=lambda: _bot,
))
app.include_router(bind_inventory_routes(
    templates=templates,
    template_context=_template_context,
    is_authenticated=is_authenticated,
    redirect_login=_redirect_login,
    redirect_back=_redirect_back,
))
app.include_router(bind_categories_routes(
    templates=templates,
    template_context=_template_context,
    is_authenticated=is_authenticated,
    redirect_login=_redirect_login,
))
app.include_router(bind_support_routes(
    templates=templates,
    template_context=_template_context,
    is_authenticated=is_authenticated,
    redirect_login=_redirect_login,
    redirect_back=_redirect_back,
    bot_getter=lambda: _bot,
))
app.include_router(bind_auth_pages_routes(
    templates=templates,
    is_authenticated=is_authenticated,
    set_admin_session=set_admin_session,
    clear_admin_session=clear_admin_session,
    login_limited=_login_limited,
    record_login_failure=_record_login_failure,
    login_failures=_login_failures,
))
app.include_router(bind_dashboard_routes(
    templates=templates,
    template_context=_template_context,
    is_authenticated=is_authenticated,
    redirect_login=_redirect_login,
    bot_getter=lambda: _bot,
))
app.include_router(bind_public_pages_routes(
    templates=templates,
))
app.include_router(bind_vouchers_routes(
    templates=templates,
    template_context=_template_context,
    is_authenticated=is_authenticated,
    redirect_login=_redirect_login,
))
app.include_router(bind_broadcasts_routes(
    templates=templates,
    template_context=_template_context,
    is_authenticated=is_authenticated,
    redirect_login=_redirect_login,
    bot_getter=lambda: _bot,
))


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


app.include_router(bind_export_routes(
    is_authenticated=is_authenticated,
    redirect_login=_redirect_login,
    csv_response=_csv_response,
))

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


# ── Root redirect ─────────────────────────────────────────────────────────────
@app.get("/")
async def root():
    return RedirectResponse("/admin", status_code=302)
