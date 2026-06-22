from fastapi import APIRouter, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload
from urllib.parse import quote

from app.database.models import Order, OrderStatus, SupportTicket, SupportTicketStatus, User, WalletTransaction, WalletTxStatus, WalletTxType
from app.database.session import async_session
from app.services import wallet_service
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
):
    @router.get("/admin/users", response_class=HTMLResponse)
    async def users_page(request: Request, msg: str = "", status: str = "", q: str = "", segment: str = "all", page: int = 1):
        if not is_authenticated(request):
            return redirect_login()

        page = max(page, 1)
        per_page = 30
        filters = []
        keyword = q.strip()

        if status == "active":
            filters.append(User.is_banned == False)
        elif status == "banned":
            filters.append(User.is_banned == True)

        if keyword:
            search_filters = [
                User.username.ilike(f"%{keyword}%"),
                User.full_name.ilike(f"%{keyword}%"),
                User.crm_tag.ilike(f"%{keyword}%"),
                User.internal_note.ilike(f"%{keyword}%"),
            ]
            if keyword.isdigit():
                search_filters.append(User.id == int(keyword))
            filters.append(or_(*search_filters))

        async with async_session() as session:
            successful_depositor_ids = select(WalletTransaction.user_id).where(
                WalletTransaction.tx_type == WalletTxType.DEPOSIT,
                WalletTransaction.status == WalletTxStatus.SUCCESS,
            )
            if segment == "repeat_buyers":
                filters.append(User.total_spent > 0)
            elif segment == "deposit_no_purchase":
                filters.append(User.id.in_(successful_depositor_ids))
                filters.append(User.total_spent <= 0)
            elif segment == "vip":
                filters.append(User.total_spent >= 500000)
            elif segment == "wallet_rich":
                filters.append(User.wallet_balance >= 200000)
            elif segment == "new_no_deposit":
                filters.append(User.total_spent <= 0)
                filters.append(~User.id.in_(successful_depositor_ids))
            total_count = await session.scalar(select(func.count(User.id)).where(*filters)) or 0
            total_pages = max((total_count + per_page - 1) // per_page, 1)
            if page > total_pages:
                page = total_pages

            segment_counts = {
                "all": await session.scalar(select(func.count(User.id))) or 0,
                "repeat_buyers": await session.scalar(select(func.count(User.id)).where(User.total_spent > 0)) or 0,
                "deposit_no_purchase": await session.scalar(
                    select(func.count(User.id)).where(
                        User.id.in_(successful_depositor_ids),
                        User.total_spent <= 0,
                    )
                ) or 0,
                "vip": await session.scalar(select(func.count(User.id)).where(User.total_spent >= 500000)) or 0,
                "wallet_rich": await session.scalar(select(func.count(User.id)).where(User.wallet_balance >= 200000)) or 0,
                "new_no_deposit": await session.scalar(select(func.count(User.id)).where(User.total_spent <= 0, ~User.id.in_(successful_depositor_ids))) or 0,
            }

            result = await session.execute(
                select(User)
                .where(*filters)
                .order_by(User.created_at.desc(), User.id.desc())
                .offset((page - 1) * per_page)
                .limit(per_page)
            )
            users = result.scalars().all()

        return templates.TemplateResponse(
            request,
            "users.html",
            template_context(
                request,
                active_page="users",
                users=users,
                msg=msg,
                current_status=status,
                current_query=q,
                current_segment=segment,
                segment_counts=segment_counts,
                current_page=page,
                total_pages=total_pages,
                total_count=total_count,
                per_page=per_page,
            ),
        )

    @router.get("/admin/users/{user_id}", response_class=HTMLResponse)
    async def user_detail_page(user_id: int, request: Request, msg: str = ""):
        if not is_authenticated(request):
            return redirect_login()

        async with async_session() as session:
            user = await session.get(User, user_id)
            if not user:
                return redirect_back("/admin/users", "Không tìm thấy người dùng")

            recent_orders_result = await session.execute(
                select(Order)
                .options(selectinload(Order.product))
                .where(Order.user_id == user_id)
                .order_by(Order.created_at.desc())
                .limit(10)
            )
            recent_orders = recent_orders_result.scalars().all()

            recent_transactions_result = await session.execute(
                select(WalletTransaction)
                .where(WalletTransaction.user_id == user_id)
                .order_by(WalletTransaction.created_at.desc())
                .limit(10)
            )
            recent_transactions = recent_transactions_result.scalars().all()

            recent_support_tickets_result = await session.execute(
                select(SupportTicket)
                .where(SupportTicket.user_id == user_id)
                .order_by(SupportTicket.updated_at.desc(), SupportTicket.id.desc())
                .limit(5)
            )
            recent_support_tickets = recent_support_tickets_result.scalars().all()

            order_count = await session.scalar(select(func.count(Order.id)).where(Order.user_id == user_id)) or 0
            completed_order_count = await session.scalar(
                select(func.count(Order.id)).where(Order.user_id == user_id, Order.status == OrderStatus.COMPLETED)
            ) or 0
            support_open_count = await session.scalar(
                select(func.count(SupportTicket.id)).where(
                    SupportTicket.user_id == user_id,
                    SupportTicket.status.in_([SupportTicketStatus.OPEN, SupportTicketStatus.ADMIN_REPLIED]),
                )
            ) or 0
            support_total_count = await session.scalar(
                select(func.count(SupportTicket.id)).where(SupportTicket.user_id == user_id)
            ) or 0
            successful_deposit_total = await session.scalar(
                select(func.sum(WalletTransaction.amount)).where(
                    WalletTransaction.user_id == user_id,
                    WalletTransaction.tx_type == WalletTxType.DEPOSIT,
                    WalletTransaction.status == WalletTxStatus.SUCCESS,
                )
            ) or 0
            latest_completed_order_at = await session.scalar(
                select(func.max(Order.completed_at)).where(
                    Order.user_id == user_id,
                    Order.status == OrderStatus.COMPLETED,
                )
            )
            latest_deposit_at = await session.scalar(
                select(func.max(WalletTransaction.completed_at)).where(
                    WalletTransaction.user_id == user_id,
                    WalletTransaction.tx_type == WalletTxType.DEPOSIT,
                    WalletTransaction.status == WalletTxStatus.SUCCESS,
                )
            )

        pref_action = request.query_params.get("prefill_action", "")
        pref_amount = request.query_params.get("prefill_amount", "")
        pref_reason = request.query_params.get("prefill_reason", "")

        return templates.TemplateResponse(
            request,
            "user_detail.html",
            template_context(
                request,
                active_page="users",
                user=user,
                recent_orders=recent_orders,
                recent_transactions=recent_transactions,
                recent_support_tickets=recent_support_tickets,
                order_count=order_count,
                completed_order_count=completed_order_count,
                support_open_count=support_open_count,
                timeline_items=sorted([
                    *[{"kind": "order", "time": order.created_at, "label": f"Đơn {order.order_code or ('DH%06d' % order.id)}", "meta": order.status.value} for order in recent_orders if order.created_at],
                    *[{"kind": "tx", "time": tx.created_at, "label": f"Giao dịch #{tx.id}", "meta": tx.tx_type.value} for tx in recent_transactions if tx.created_at],
                    *[{"kind": "ticket", "time": ticket.updated_at or ticket.created_at, "label": f"Ticket #{ticket.id}", "meta": ticket.status.value} for ticket in recent_support_tickets if (ticket.updated_at or ticket.created_at)],
                ], key=lambda item: item["time"], reverse=True)[:12],
                support_total_count=support_total_count,
                successful_deposit_total=successful_deposit_total,
                latest_completed_order_at=latest_completed_order_at,
                latest_deposit_at=latest_deposit_at,
                msg=msg,
                prefill_action=pref_action,
                prefill_amount=pref_amount,
                prefill_reason=pref_reason,
            ),
        )

    @router.post("/admin/users/{user_id}/toggle-ban")
    async def toggle_user_ban_web(user_id: int, request: Request, csrf_token: str = Form(...), ban_action: str = Form(...)):
        if not is_authenticated(request):
            return redirect_login()
        if not validate_csrf_token(request, csrf_token):
            return Response("CSRF token không hợp lệ", status_code=403)

        async with async_session() as session:
            user = await session.get(User, user_id)
            if not user:
                return redirect_back("/admin/users", "Không tìm thấy người dùng")
            if ban_action == "ban":
                user.is_banned = True
                msg = f"Đã cấm user {user_id}"
                audit_action = "web_user_ban"
            elif ban_action == "unban":
                user.is_banned = False
                msg = f"Đã mở cấm user {user_id}"
                audit_action = "web_user_unban"
            else:
                return redirect_back(f"/admin/users/{user_id}", "Hành động không hợp lệ")
            await session.commit()

        write_audit_event(request, audit_action, target_user_id=user_id)
        referer = request.headers.get("referer", "")
        if f"/admin/users/{user_id}" in referer:
            return redirect_back(f"/admin/users/{user_id}", msg)
        return redirect_back("/admin/users", msg)

    @router.post("/admin/users/{user_id}/crm")
    async def update_user_crm_web(
        user_id: int,
        request: Request,
        csrf_token: str = Form(...),
        crm_tag: str = Form(""),
        internal_note: str = Form(""),
    ):
        if not is_authenticated(request):
            return redirect_login()
        if not validate_csrf_token(request, csrf_token):
            return Response("CSRF token không hợp lệ", status_code=403)

        async with async_session() as session:
            user = await session.get(User, user_id)
            if not user:
                return redirect_back("/admin/users", "Không tìm thấy người dùng")
            user.crm_tag = crm_tag.strip() or None
            user.internal_note = internal_note.strip() or None
            await session.commit()

        write_audit_event(request, "user_crm_update", target_user_id=user_id, crm_tag=crm_tag.strip() or None)
        return redirect_back(f"/admin/users/{user_id}", "Đã lưu thông tin CRM nội bộ")

    @router.post("/admin/users/{user_id}/wallet-adjust")
    async def user_wallet_adjustment_web(
        user_id: int,
        request: Request,
        csrf_token: str = Form(...),
        amount: str = Form(...),
        action: str = Form(...),
        reason: str = Form(...),
    ):
        if not is_authenticated(request):
            return redirect_login()
        if not has_payment_access(request):
            unlock_url = (
                f"/admin/payments/unlock?return_to={quote(f'/admin/users/{user_id}', safe='')}"
                f"&user_id={user_id}&action={quote(action, safe='')}"
                f"&amount={quote(amount, safe='')}&reason={quote(reason, safe='')}"
            )
            return RedirectResponse(unlock_url, status_code=302)
        if not validate_csrf_token(request, csrf_token):
            return Response("CSRF token không hợp lệ", status_code=403)

        actor = get_admin_actor(request)
        tx_type_map = {
            "refund": WalletTxType.REFUND,
            "credit": WalletTxType.ADMIN_CREDIT,
            "debit": WalletTxType.ADMIN_DEBIT,
        }
        tx_type = tx_type_map.get(action)
        if not tx_type:
            return redirect_back(f"/admin/users/{user_id}", "Loại điều chỉnh ví không hợp lệ")

        async with async_session() as session:
            result = await wallet_service.adjust_wallet_balance(session, user_id, amount, tx_type, actor, reason)

        write_audit_event(request, "user_wallet_adjustment", actor=actor, user_id=user_id, amount=amount, adjustment_type=action, success=result.success, reason=reason, tx_id=result.transaction.id if result.transaction else None)
        referer = request.headers.get("referer", "")
        target = f"/admin/users/{user_id}" if f"/admin/users/{user_id}" in referer else "/admin/users"
        return redirect_back(target, result.message)

    return router
