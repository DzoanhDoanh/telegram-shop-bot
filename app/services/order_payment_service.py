from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.models import InventoryItem, Order, OrderStatus
from app.services import delivery_service


@dataclass(slots=True)
class OrderPaymentResult:
    success: bool
    message: str
    order: Order | None = None
    items_delivered: int = 0


async def get_order_for_payment(session: AsyncSession, order_id: int) -> Order | None:
    result = await session.execute(
        select(Order)
        .options(selectinload(Order.product), selectinload(Order.user))
        .where(Order.id == order_id)
        .with_for_update()
    )
    return result.scalar_one_or_none()


async def mark_order_paid(
    session: AsyncSession,
    order: Order,
    payment_method: str | None = None,
    payment_note: str | None = None,
    paid_at: datetime | None = None,
) -> OrderPaymentResult:
    if order.status not in {OrderStatus.PENDING_PAYMENT, OrderStatus.PAID}:
        return OrderPaymentResult(False, "Đơn hàng không còn ở trạng thái chờ thanh toán.", order)

    now = paid_at or datetime.utcnow()
    if payment_method:
        order.payment_method = payment_method
    if payment_note:
        existing_note = (order.payment_note or "").strip()
        order.payment_note = f"{existing_note}\n{payment_note}".strip() if existing_note else payment_note
    if order.status == OrderStatus.PENDING_PAYMENT:
        order.status = OrderStatus.PAID
    if not order.paid_at:
        order.paid_at = now
    await session.flush()
    return OrderPaymentResult(True, "Đã ghi nhận thanh toán đơn hàng.", order)


async def complete_paid_order(
    session: AsyncSession,
    bot: Bot,
    order: Order,
) -> OrderPaymentResult:
    if order.status == OrderStatus.COMPLETED:
        return OrderPaymentResult(True, "Đơn hàng đã hoàn tất trước đó.", order, int(order.quantity or 0))

    if order.status == OrderStatus.PENDING_PAYMENT:
        paid_result = await mark_order_paid(session, order)
        if not paid_result.success:
            return paid_result

    delivery_result = await delivery_service.deliver_paid_order(session, bot, order)
    if not delivery_result.success:
        return OrderPaymentResult(False, delivery_result.message, delivery_result.order)
    return OrderPaymentResult(True, delivery_result.message, delivery_result.order, delivery_result.items_delivered)


async def list_reserved_inventory_items(session: AsyncSession, order_id: int) -> list[InventoryItem]:
    result = await session.execute(
        select(InventoryItem)
        .where(InventoryItem.order_id == order_id)
        .order_by(InventoryItem.id.asc())
    )
    return list(result.scalars().all())
