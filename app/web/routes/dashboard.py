from datetime import datetime, timedelta

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database.models import InventoryItem, Order, OrderStatus, Product, SupportTicket, SupportTicketStatus, User, WalletTransaction, WalletTxStatus
from app.database.session import async_session
from app.services import wallet_service

router = APIRouter()


def bind_routes(templates, template_context, is_authenticated, redirect_login, bot_getter):
    @router.get("/admin/preflight")
    async def admin_preflight(request: Request):
        if not is_authenticated(request):
            return redirect_login()

        checks = {
            "bot_token": bool(settings.BOT_TOKEN),
            "admin_password_changed": settings.ADMIN_PASSWORD != "admin_secret",
            "session_secret_changed": settings.SESSION_SECRET != "change_me_session_secret",
            "payment_admin_pin": bool(settings.PAYMENT_ADMIN_PIN),
            "bot_ready": bot_getter() is not None,
        }
        async with async_session() as session:
            config = await wallet_service.get_active_payment_config(session)
            checks.update({
                "payment_account_configured": bool(config and config.account_no and config.bank_name),
                "webhook_provider_configured": bool(config and config.webhook_provider),
                "webhook_secret_configured": bool((config and config.webhook_secret) or settings.BANK_WEBHOOK_SECRET),
            })
        return checks

    @router.get("/health")
    async def health_check():
        health = {"status": "ok", "database": False, "redis": False, "bot_ready": bot_getter() is not None}
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

    @router.get("/admin", response_class=HTMLResponse)
    async def dashboard(request: Request):
        if not is_authenticated(request):
            return redirect_login()

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
            open_support_tickets = await session.scalar(
                select(func.count(SupportTicket.id)).where(SupportTicket.status == SupportTicketStatus.OPEN)
            ) or 0
            admin_replied_tickets = await session.scalar(
                select(func.count(SupportTicket.id)).where(SupportTicket.status == SupportTicketStatus.ADMIN_REPLIED)
            ) or 0
            new_users_7d = await session.scalar(
                select(func.count(User.id)).where(User.created_at >= datetime.utcnow() - timedelta(days=7))
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

            result = await session.execute(
                select(Order)
                .options(selectinload(Order.product), selectinload(Order.user))
                .order_by(Order.created_at.desc())
                .limit(8)
            )
            recent_orders = result.scalars().all()

            top_customers_result = await session.execute(
                select(User)
                .where(User.total_spent > 0)
                .order_by(User.total_spent.desc(), User.wallet_balance.desc(), User.id.desc())
                .limit(5)
            )
            top_customers = top_customers_result.scalars().all()

            recent_support_result = await session.execute(
                select(SupportTicket)
                .options(selectinload(SupportTicket.user))
                .order_by(SupportTicket.updated_at.desc(), SupportTicket.id.desc())
                .limit(6)
            )
            recent_support_tickets = recent_support_result.scalars().all()

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

        return templates.TemplateResponse(
            request,
            "dashboard.html",
            template_context(
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
                    "open_support_tickets": open_support_tickets,
                    "admin_replied_tickets": admin_replied_tickets,
                    "new_users_7d": new_users_7d,
                },
                recent_orders=recent_orders,
                recent_support_tickets=recent_support_tickets,
                top_customers=top_customers,
                low_stock_products=low_stock_products,
                chart_labels=chart_labels,
                chart_data=chart_data,
            ),
        )

    return router
