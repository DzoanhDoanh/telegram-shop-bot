from dataclasses import dataclass
from datetime import datetime
from html import escape
import logging

from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.models import InventoryItem, Order, OrderStatus
from app.services.order_code import get_order_code

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class DeliveryResult:
    success: bool
    message: str
    order: Order | None = None
    items_delivered: int = 0


async def _load_order_for_delivery(session: AsyncSession, order_id: int) -> Order | None:
    result = await session.execute(
        select(Order)
        .options(selectinload(Order.product), selectinload(Order.user))
        .where(Order.id == order_id)
        .with_for_update()
    )
    return result.scalar_one_or_none()


async def _reserve_inventory(session: AsyncSession, order: Order) -> list[InventoryItem]:
    result = await session.execute(
        select(InventoryItem)
        .where(
            InventoryItem.product_id == order.product_id,
            InventoryItem.is_sold == False,
        )
        .order_by(InventoryItem.id.asc())
        .limit(order.quantity)
        .with_for_update(skip_locked=True)
    )
    return list(result.scalars().all())


def _build_delivery_text(order: Order, items: list[InventoryItem]) -> str:
    product = order.product
    product_name = escape(product.name if product else "sản phẩm")
    order_code = escape(get_order_code(order))
    lines = [
        f"🎉 <b>Đơn hàng {order_code} đã hoàn tất!</b>",
        "",
        f"Mã đơn hàng: <b>{order_code}</b>",
        f"Sản phẩm: <b>{product_name}</b>",
        f"Số lượng: <b>{order.quantity}</b>",
        "",
    ]
    if product and getattr(product, "delivery_mode", "inventory") == "fixed_content":
        fixed_content = (product.fixed_delivery_content or "").strip()
        lines.extend([
            "📩 <b>Nội dung bạn nhận được:</b>",
            escape(fixed_content),
        ])
    else:
        lines.append("📩 <b>Thông tin sản phẩm bạn nhận được:</b>")
        lines.append("")
        for index, item in enumerate(items, 1):
            lines.append(f"{index}. <code>{escape(item.content)}</code>")
    lines.extend([
        "",
        "Nếu có vấn đề với đơn hàng, hãy dùng đúng mã đơn này để shop hỗ trợ nhanh hơn.",
        "Cảm ơn bạn đã mua sắm tại shop!",
    ])
    return "\n".join(lines)


async def deliver_paid_order(session: AsyncSession, bot: Bot, order: Order) -> DeliveryResult:
    if order.status not in {OrderStatus.PAID, OrderStatus.PENDING_PAYMENT}:
        return DeliveryResult(False, "Đơn hàng không ở trạng thái có thể giao.", order)

    items: list[InventoryItem] = []
    if order.product and getattr(order.product, "delivery_mode", "inventory") == "fixed_content":
        if not (order.product.fixed_delivery_content or "").strip():
            await session.rollback()
            return DeliveryResult(False, "Sản phẩm này chưa được cấu hình nội dung giao cho khách.", order)
    else:
        items = await _reserve_inventory(session, order)
        if len(items) < order.quantity:
            await session.rollback()
            return DeliveryResult(
                False,
                f"Không đủ hàng trong kho. Cần {order.quantity}, còn {len(items)}.",
                order,
            )

    delivery_text = _build_delivery_text(order, items)

    try:
        await bot.send_message(chat_id=order.user_id, text=delivery_text)
    except Exception:
        logger.exception("Failed to deliver order", extra={"order_id": order.id, "user_id": order.user_id})
        await session.rollback()
        return DeliveryResult(False, "Telegram gửi hàng thất bại. Đơn vẫn chờ xử lý.", order)

    now = datetime.utcnow()
    for item in items:
        item.is_sold = True
        item.sold_at = now
        item.order_id = order.id

    order.status = OrderStatus.COMPLETED
    if not order.paid_at:
        order.paid_at = now
    order.completed_at = now
    await session.commit()
    await session.refresh(order)
    return DeliveryResult(True, f"Đã giao {len(items)} mục sản phẩm.", order, len(items))


async def approve_and_deliver_order(session: AsyncSession, bot: Bot, order_id: int) -> DeliveryResult:
    order = await _load_order_for_delivery(session, order_id)
    if not order or order.status != OrderStatus.PENDING_PAYMENT:
        return DeliveryResult(False, "Đơn hàng không tồn tại hoặc đã được xử lý.")

    order.status = OrderStatus.PAID
    if not order.paid_at:
        order.paid_at = datetime.utcnow()
    await session.flush()
    return await deliver_paid_order(session, bot, order)


async def deliver_order(session: AsyncSession, bot: Bot, order: Order) -> bool:
    result = await deliver_paid_order(session, bot, order)
    return result.success
