from datetime import datetime, timedelta
from html import escape

import sqlalchemy as sa
from aiogram import Bot
from fastapi import APIRouter, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database.models import Order, OrderStatus, Product
from app.database.session import async_session
from app.services import delivery_service, order_service, payment_policy_service, wallet_service
from app.services.order_code import get_order_code
from app.web.audit import write_audit_event
from app.web.auth import get_admin_actor, validate_csrf_token

router = APIRouter()


def bind_routes(
    templates,
    template_context,
    is_authenticated,
    redirect_login,
    redirect_back,
    has_payment_access,
    bot_getter,
):
    @router.get("/admin/orders", response_class=HTMLResponse)
    async def orders_page(
        request: Request,
        status: str = "all",
        msg: str = "",
        q: str = "",
        product_id: str = "",
        date_from: str = "",
        date_to: str = "",
        page: int = 1,
    ):
        if not is_authenticated(request):
            return redirect_login()

        try:
            selected_product_id = int(product_id) if product_id else None
        except ValueError:
            selected_product_id = None

        page = max(page, 1)
        per_page = 30

        async with async_session() as session:
            order_query = select(Order).options(
                selectinload(Order.product), selectinload(Order.user)
            )

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

            count_query = select(func.count()).select_from(order_query.order_by(None).subquery())
            total_count = await session.scalar(count_query) or 0
            total_pages = max((total_count + per_page - 1) // per_page, 1)
            if page > total_pages:
                page = total_pages

            summary_counts = {
                "all": await session.scalar(select(func.count(Order.id))) or 0,
                "pending_payment": await session.scalar(select(func.count(Order.id)).where(Order.status == OrderStatus.PENDING_PAYMENT)) or 0,
                "completed": await session.scalar(select(func.count(Order.id)).where(Order.status == OrderStatus.COMPLETED)) or 0,
                "cancelled": await session.scalar(select(func.count(Order.id)).where(Order.status == OrderStatus.CANCELLED)) or 0,
            }

            paged_query = order_query.order_by(Order.created_at.desc(), Order.id.desc()).offset((page - 1) * per_page).limit(per_page)
            result = await session.execute(paged_query)
            orders = result.scalars().all()
            for order in orders:
                order.display_code = get_order_code(order)
                order.payment_method_label = payment_policy_service.get_payment_method_label(order.payment_method)

        return templates.TemplateResponse(
            request,
            "orders.html",
            template_context(
                request,
                active_page="orders",
                orders=orders,
                products=products,
                current_status=status,
                q=q,
                product_id=selected_product_id,
                date_from=date_from,
                date_to=date_to,
                current_page=page,
                total_pages=total_pages,
                total_count=total_count,
                per_page=per_page,
                summary_counts=summary_counts,
                msg=msg,
            ),
        )

    @router.get("/admin/orders/{order_id}/bill")
    async def order_bill(order_id: int, request: Request):
        if not is_authenticated(request):
            return redirect_login()
        bot = bot_getter()
        if not bot:
            return RedirectResponse("/admin/orders?msg=Bot chưa sẵn sàng để tải bill", status_code=302)

        async with async_session() as session:
            order = await session.get(Order, order_id)
            if not order or not order.payment_proof:
                return RedirectResponse("/admin/orders?msg=Đơn không có bill", status_code=302)

        try:
            file = await bot.get_file(order.payment_proof)
        except Exception:
            return RedirectResponse("/admin/orders?msg=Không tải được bill từ Telegram", status_code=302)

        return RedirectResponse(
            f"https://api.telegram.org/file/bot{settings.BOT_TOKEN}/{file.file_path}",
            status_code=302,
        )

    @router.post("/admin/orders/{order_id}/approve")
    async def approve_order_web(order_id: int, request: Request, csrf_token: str = Form(...)):
        if not is_authenticated(request):
            return redirect_login()
        if not validate_csrf_token(request, csrf_token):
            return RedirectResponse('/login', status_code=302)

        bot = bot_getter()
        if not bot:
            return RedirectResponse(
                f"/admin/orders?status=pending_payment&msg=Bot chưa sẵn sàng, chưa thể giao đơn #{order_id}",
                status_code=302,
            )

        async with async_session() as session:
            result = await delivery_service.approve_and_deliver_order(session, bot, order_id)

        write_audit_event(request, "order_approve", order_id=order_id)
        return RedirectResponse(
            f"/admin/orders?status=pending_payment&msg={result.message}",
            status_code=302,
        )

    @router.post("/admin/orders/{order_id}/reject")
    async def reject_order_web(
        order_id: int,
        request: Request,
        reason: str = Form(""),
        csrf_token: str = Form(...),
    ):
        if not is_authenticated(request):
            return redirect_login()
        if not validate_csrf_token(request, csrf_token):
            return RedirectResponse('/login', status_code=302)

        bot = bot_getter()
        async with async_session() as session:
            order = await order_service.reject_order(session, order_id, reason)
            if order and bot:
                reject_reason = escape(reason.strip() or 'Thanh toán chưa hợp lệ hoặc chưa xác minh được.')
                order_code = escape(get_order_code(order))
                try:
                    await bot.send_message(
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

    @router.post("/admin/orders/{order_id}/refund")
    async def refund_order_web(
        order_id: int,
        request: Request,
        csrf_token: str = Form(...),
        reason: str = Form(...),
    ):
        if not is_authenticated(request):
            return redirect_login()
        if not has_payment_access(request):
            return RedirectResponse("/admin/payments/unlock", status_code=302)
        if not validate_csrf_token(request, csrf_token):
            return Response("CSRF token không hợp lệ", status_code=403)

        actor = get_admin_actor(request)
        refunded_order = None
        bot = bot_getter()
        async with async_session() as session:
            result = await wallet_service.refund_order_to_wallet(session, order_id, actor, reason)
            refunded_order = result.order

        if result.success and refunded_order and bot:
            try:
                await bot.send_message(
                    chat_id=refunded_order.user_id,
                    text=(
                        f"💸 <b>Đơn hàng {get_order_code(refunded_order)} đã được hoàn tiền</b>\n\n"
                        f"Số tiền đã hoàn: <b>{wallet_service.format_vnd(refunded_order.total_amount)}</b>\n"
                        f"Lý do: {escape(reason.strip())}\n\n"
                        "Tiền đã được cộng lại vào ví của bạn."
                    ),
                )
            except Exception:
                pass

        write_audit_event(
            request,
            "order_refund",
            actor=actor,
            order_id=order_id,
            success=result.success,
            reason=reason,
            tx_id=result.transaction.id if result.transaction else None,
        )
        return redirect_back("/admin/orders", result.message)

    return router
