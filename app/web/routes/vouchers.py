from datetime import datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import quote

from fastapi import APIRouter, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select

from app.database.models import Category, Product, Voucher, VoucherDiscountType
from app.database.session import async_session
from app.services import voucher_service
from app.web.audit import write_audit_event
from app.web.auth import validate_csrf_token

router = APIRouter()


def _parse_decimal(value: str, default: str = "0") -> Decimal:
    try:
        return Decimal((value or default).replace(",", "").strip() or default)
    except (InvalidOperation, ValueError):
        return Decimal(default)


def _parse_datetime(value: str) -> datetime | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def bind_routes(templates, template_context, is_authenticated, redirect_login):
    @router.get("/admin/vouchers", response_class=HTMLResponse)
    async def vouchers_page(request: Request, msg: str = ""):
        if not is_authenticated(request):
            return redirect_login()
        async with async_session() as session:
            vouchers = await voucher_service.list_vouchers(session)
            categories = list((await session.execute(select(Category).where(Category.is_active == True).order_by(Category.name.asc()))).scalars().all())
            products = list((await session.execute(select(Product).where(Product.is_active == True).order_by(Product.name.asc()))).scalars().all())
        return templates.TemplateResponse(
            request,
            "vouchers.html",
            template_context(
                request,
                active_page="vouchers",
                msg=msg,
                vouchers=vouchers,
                categories=categories,
                products=products,
            ),
        )

    @router.post("/admin/vouchers/add")
    async def add_voucher(
        request: Request,
        csrf_token: str = Form(...),
        code: str = Form(...),
        name: str = Form(""),
        description: str = Form(""),
        discount_type: str = Form("amount"),
        discount_value: str = Form("0"),
        min_order_amount: str = Form("0"),
        max_discount_amount: str = Form(""),
        usage_limit: str = Form(""),
        starts_at: str = Form(""),
        expires_at: str = Form(""),
        applies_product_id: str = Form(""),
        applies_category_id: str = Form(""),
        is_active: str = Form("off"),
    ):
        if not is_authenticated(request):
            return redirect_login()
        if not validate_csrf_token(request, csrf_token):
            return Response("CSRF token không hợp lệ", status_code=403)

        normalized_code = voucher_service.normalize_code(code)
        if not normalized_code:
            return RedirectResponse("/admin/vouchers?msg=" + quote("Mã voucher không được để trống"), status_code=302)

        async with async_session() as session:
            existing = await voucher_service.get_active_voucher_by_code(session, normalized_code)
            if existing:
                return RedirectResponse("/admin/vouchers?msg=" + quote("Mã voucher đã tồn tại"), status_code=302)
            voucher = Voucher(
                code=normalized_code,
                name=name.strip() or None,
                description=description.strip() or None,
                discount_type=VoucherDiscountType.PERCENT if discount_type == "percent" else VoucherDiscountType.AMOUNT,
                discount_value=max(Decimal("0"), _parse_decimal(discount_value)),
                min_order_amount=max(Decimal("0"), _parse_decimal(min_order_amount)),
                max_discount_amount=max(Decimal("0"), _parse_decimal(max_discount_amount)) if max_discount_amount.strip() else None,
                usage_limit=max(1, int(usage_limit)) if usage_limit.strip().isdigit() else None,
                starts_at=_parse_datetime(starts_at),
                expires_at=_parse_datetime(expires_at),
                applies_product_id=int(applies_product_id) if applies_product_id.strip().isdigit() else None,
                applies_category_id=int(applies_category_id) if applies_category_id.strip().isdigit() else None,
                is_active=is_active == "on",
            )
            session.add(voucher)
            await session.commit()
            voucher_id = voucher.id
        write_audit_event(request, "voucher_add", voucher_id=voucher_id, code=normalized_code)
        return RedirectResponse("/admin/vouchers?msg=" + quote("Đã tạo voucher"), status_code=302)

    @router.post("/admin/vouchers/{voucher_id}/toggle")
    async def toggle_voucher(voucher_id: int, request: Request, csrf_token: str = Form(...)):
        if not is_authenticated(request):
            return redirect_login()
        if not validate_csrf_token(request, csrf_token):
            return Response("CSRF token không hợp lệ", status_code=403)
        async with async_session() as session:
            voucher = await session.get(Voucher, voucher_id)
            if not voucher:
                return RedirectResponse("/admin/vouchers?msg=" + quote("Không tìm thấy voucher"), status_code=302)
            voucher.is_active = not voucher.is_active
            await session.commit()
            is_active = voucher.is_active
            code = voucher.code
        write_audit_event(request, "voucher_toggle", voucher_id=voucher_id, code=code, is_active=is_active)
        return RedirectResponse("/admin/vouchers?msg=" + quote("Đã cập nhật trạng thái voucher"), status_code=302)

    return router
