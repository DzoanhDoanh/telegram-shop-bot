from fastapi import APIRouter, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload
from urllib.parse import quote
import hmac

from app.config import settings
from app.database.models import Order, WalletTransaction, WalletTxStatus, WalletTxType
from app.database.session import async_session
from app.services import payment_policy_service, wallet_service
from app.web.audit import client_ip, write_audit_event
from app.web.auth import get_admin_actor, validate_csrf_token

router = APIRouter()


def bind_routes(
    templates,
    template_context,
    is_authenticated,
    redirect_login,
    has_payment_access,
    set_payment_access,
    payment_unlock_limited,
    record_payment_unlock_failure,
    redirect_back,
):
    @router.get("/admin/payments/unlock", response_class=HTMLResponse)
    async def payments_unlock_page(
        request: Request,
        error: str = "",
        return_to: str = "/admin/payments",
        user_id: str = "",
        action: str = "",
        amount: str = "",
        reason: str = "",
    ):
        if not is_authenticated(request):
            return redirect_login()
        return templates.TemplateResponse(
            request,
            "payments_unlock.html",
            template_context(
                request,
                active_page="payments",
                error=error,
                return_to=return_to,
                user_id=user_id,
                action=action,
                amount=amount,
                reason=reason,
            ),
        )

    @router.post("/admin/payments/unlock")
    async def payments_unlock_web(
        request: Request,
        csrf_token: str = Form(...),
        pin: str = Form(...),
        return_to: str = Form("/admin/payments"),
        user_id: str = Form(""),
        action: str = Form(""),
        amount: str = Form(""),
        reason: str = Form(""),
    ):
        if not is_authenticated(request):
            return redirect_login()
        if not validate_csrf_token(request, csrf_token):
            return Response("CSRF token không hợp lệ", status_code=403)

        ip = client_ip(request)
        unlock_query = f"return_to={quote(return_to or '/admin/payments', safe='')}" \
            f"&user_id={quote(user_id, safe='')}&action={quote(action, safe='')}" \
            f"&amount={quote(amount, safe='')}&reason={quote(reason, safe='')}"

        if payment_unlock_limited(ip):
            write_audit_event(request, "payment_unlock_rate_limited")
            return RedirectResponse(f"/admin/payments/unlock?error=Bạn nhập sai quá nhiều lần, vui lòng thử lại sau&{unlock_query}", status_code=302)

        expected_pin = settings.PAYMENT_ADMIN_PIN
        if not expected_pin or not hmac.compare_digest(pin, expected_pin):
            record_payment_unlock_failure(ip)
            write_audit_event(request, "payment_unlock_failed")
            return RedirectResponse(f"/admin/payments/unlock?error=Mã bảo vệ không đúng&{unlock_query}", status_code=302)

        write_audit_event(request, "payment_unlock_success")
        target_url = return_to or "/admin/payments"
        if target_url.startswith("/admin/users/") and user_id:
            joiner = "&" if "?" in target_url else "?"
            target_url = (
                f"{target_url}{joiner}prefill_action={quote(action, safe='')}"
                f"&prefill_amount={quote(amount, safe='')}"
                f"&prefill_reason={quote(reason, safe='')}"
            )
        response = RedirectResponse(target_url, status_code=302)
        set_payment_access(response)
        return response

    @router.get("/admin/payments", response_class=HTMLResponse)
    async def payments_page(request: Request, msg: str = "", status: str = "", q: str = "", page: int = 1):
        if not is_authenticated(request):
            return redirect_login()
        if not has_payment_access(request):
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

            total_count = await session.scalar(select(func.count(WalletTransaction.id)).where(*filters)) or 0
            total_pages = max((total_count + per_page - 1) // per_page, 1)
            if page > total_pages:
                page = total_pages

            success_total_amount = await session.scalar(
                select(func.sum(WalletTransaction.amount)).where(
                    WalletTransaction.status == WalletTxStatus.SUCCESS,
                    WalletTransaction.tx_type == WalletTxType.DEPOSIT,
                )
            ) or 0
            pending_total_amount = await session.scalar(
                select(func.sum(WalletTransaction.amount)).where(WalletTransaction.status == WalletTxStatus.PENDING)
            ) or 0

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
            direct_bank_orders = await session.execute(
                select(Order)
                .options(selectinload(Order.user), selectinload(Order.product))
                .where(Order.payment_method == payment_policy_service.PAYMENT_METHOD_DIRECT_BANK)
                .order_by(Order.created_at.desc())
                .limit(20)
            )
            direct_bank_orders = list(direct_bank_orders.scalars().all())
            for order in direct_bank_orders:
                order.payment_method_label = payment_policy_service.get_payment_method_label(order.payment_method)
            review_counts = {
                "pending": await session.scalar(select(func.count(WalletTransaction.id)).where(WalletTransaction.status == WalletTxStatus.PENDING)) or 0,
                "underpaid": await session.scalar(select(func.count(WalletTransaction.id)).where(WalletTransaction.status == WalletTxStatus.UNDERPAID)) or 0,
                "review_required": await session.scalar(select(func.count(WalletTransaction.id)).where(WalletTransaction.status == WalletTxStatus.REVIEW_REQUIRED)) or 0,
                "late_paid": await session.scalar(select(func.count(WalletTransaction.id)).where(WalletTransaction.status == WalletTxStatus.LATE_PAID)) or 0,
            }

        return templates.TemplateResponse(
            request,
            "payments.html",
            template_context(
                request,
                active_page="payments",
                msg=msg,
                config=config,
                transactions=transactions,
                current_status=status,
                review_counts=review_counts,
                success_total_amount=success_total_amount,
                pending_total_amount=pending_total_amount,
                current_query=q,
                current_page=page,
                total_pages=total_pages,
                total_count=total_count,
                per_page=per_page,
                direct_bank_orders=direct_bank_orders,
            ),
        )

    @router.post("/admin/payments/config")
    async def update_payment_config_web(
        request: Request,
        csrf_token: str = Form(...),
        bank_name: str = Form(""),
        account_no: str = Form(""),
        account_name: str = Form(""),
        vietqr_bank_code: str = Form(""),
        webhook_secret: str = Form(""),
        webhook_provider: str = Form(""),
        min_deposit_enabled: str = Form("off"),
        min_deposit_amount: str = Form("0"),
    ):
        if not is_authenticated(request):
            return redirect_login()
        if not has_payment_access(request):
            return RedirectResponse("/admin/payments/unlock", status_code=302)
        if not validate_csrf_token(request, csrf_token):
            return Response("CSRF token không hợp lệ", status_code=403)

        min_deposit_amount_value = wallet_service.money(min_deposit_amount or 0)
        if min_deposit_amount_value < 0:
            min_deposit_amount_value = wallet_service.money(0)

        async with async_session() as session:
            config = await wallet_service.ensure_payment_config(session)
            config.bank_name = bank_name.strip() or None
            config.account_no = account_no.strip() or None
            config.account_name = account_name.strip() or None
            config.vietqr_bank_code = vietqr_bank_code.strip() or None
            if webhook_secret.strip():
                config.webhook_secret = webhook_secret.strip()
            config.webhook_provider = webhook_provider.strip().lower() or None
            config.min_deposit_enabled = min_deposit_enabled == "on"
            config.min_deposit_amount = min_deposit_amount_value
            config.is_active = True
            await session.commit()

        write_audit_event(request, "update_payment_config")
        return redirect_back("/admin/payments", "Đã lưu cấu hình thanh toán")

    @router.post("/admin/payments/wallet-transactions/{tx_id}/cancel")
    async def cancel_wallet_transaction_web(
        tx_id: int,
        request: Request,
        csrf_token: str = Form(...),
        reason: str = Form("Admin hủy giao dịch pending"),
    ):
        if not is_authenticated(request):
            return redirect_login()
        if not has_payment_access(request):
            return RedirectResponse("/admin/payments/unlock", status_code=302)
        if not validate_csrf_token(request, csrf_token):
            return Response("CSRF token không hợp lệ", status_code=403)

        actor = get_admin_actor(request)
        async with async_session() as session:
            result = await wallet_service.cancel_wallet_transaction_admin(session, tx_id, actor, reason)

        write_audit_event(request, "cancel_wallet_transaction", tx_id=tx_id, actor=actor, success=result.success, reason=reason)
        return redirect_back("/admin/payments", result.message)

    @router.post("/admin/payments/wallet-adjust")
    async def wallet_adjustment_web(
        request: Request,
        csrf_token: str = Form(...),
        user_id: int = Form(...),
        amount: str = Form(...),
        action: str = Form(...),
        reason: str = Form(...),
    ):
        if not is_authenticated(request):
            return redirect_login()
        if not has_payment_access(request):
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
            return redirect_back("/admin/payments", "Loại điều chỉnh ví không hợp lệ")

        async with async_session() as session:
            result = await wallet_service.adjust_wallet_balance(session, user_id, amount, tx_type, actor, reason)

        write_audit_event(request, "wallet_adjustment", actor=actor, user_id=user_id, amount=amount, adjustment_type=action, success=result.success, reason=reason, tx_id=result.transaction.id if result.transaction else None)
        return redirect_back("/admin/payments", result.message)

    return router
