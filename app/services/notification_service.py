import html
import logging

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.models import InventoryItem, Product, User

logger = logging.getLogger(__name__)

MAX_PRODUCT_ANNOUNCEMENTS = 200
ANNOUNCEMENT_TYPE_NEW = "new"
ANNOUNCEMENT_TYPE_REMINDER = "reminder"


def _announcement_title(kind: str) -> str:
    if kind == ANNOUNCEMENT_TYPE_REMINDER:
        return "📢 <b>Sản phẩm đang có sẵn, bạn có thể xem lại</b>"
    return "🆕 <b>Sản phẩm mới vừa lên kệ!</b>"


async def announce_product(bot: Bot | None, session: AsyncSession, product_id: int, kind: str = ANNOUNCEMENT_TYPE_NEW) -> int:
    if bot is None:
        return 0

    product = await session.get(Product, product_id, options=[selectinload(Product.category)])
    if not product or not product.is_active:
        return 0

    stock = await session.scalar(
        select(func.count(InventoryItem.id)).where(
            InventoryItem.product_id == product_id,
            InventoryItem.is_sold == False,
        )
    ) or 0
    if product.delivery_mode != "fixed_content" and stock <= 0:
        return 0

    result = await session.execute(
        select(User.id)
        .where(User.is_banned == False)
        .order_by(User.created_at.asc())
        .limit(MAX_PRODUCT_ANNOUNCEMENTS)
    )
    user_ids = list(result.scalars().all())

    category_name = product.category.name if product.category else "Khác"
    description = (product.description or "").strip()
    text_parts = [
        _announcement_title(kind),
        "",
        f"📦 Tên: <b>{html.escape(product.name)}</b>",
        f"💰 Giá: <b>{product.price:,.0f}đ</b>",
        f"🏷 Danh mục: <b>{html.escape(category_name)}</b>",
    ]
    if product.delivery_mode != "fixed_content":
        text_parts.append(f"📦 Tồn kho hiện tại: <b>{int(stock)}</b>")
    if description:
        text_parts.extend(["", f"📝 Mô tả: {html.escape(description[:300])}"])
    text_parts.extend(["", "Bấm nút bên dưới để xem chi tiết và mua ngay."])

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🛒 Xem sản phẩm", callback_data=f"prod_{product.id}")]
        ]
    )

    sent = 0
    for user_id in user_ids:
        try:
            await bot.send_message(user_id, "\n".join(text_parts), reply_markup=keyboard)
            sent += 1
        except Exception:
            logger.exception("Failed to send product announcement", extra={"product_id": product.id, "user_id": user_id, "kind": kind})
            continue

    return sent


async def announce_new_product(bot: Bot | None, session: AsyncSession, product_id: int) -> int:
    return await announce_product(bot, session, product_id, ANNOUNCEMENT_TYPE_NEW)
