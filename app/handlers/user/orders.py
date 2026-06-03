import html

from aiogram import Router, F, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database.session import async_session
from app.config import settings
from app.database.models import Order, User
from app.keyboards.user_kb import get_persistent_menu_kb

router = Router()


STATUS_TEXT = {
    "pending_payment": "⏳ Chờ thanh toán",
    "paid": "💸 Đã thanh toán",
    "completed": "✅ Hoàn thành",
    "cancelled": "❌ Đã hủy",
    "refunded": "🔄 Hoàn tiền",
}


async def _ensure_user_allowed(message: types.Message) -> bool:
    async with async_session() as session:
        user = await session.get(User, message.from_user.id)
        if user and user.is_banned:
            await message.answer(
                "🚫 Tài khoản của bạn đã bị cấm sử dụng bot.",
                reply_markup=get_persistent_menu_kb(),
            )
            return False
    return True


def _format_order(order: Order) -> str:
    status_value = order.status.value
    status_text = STATUS_TEXT.get(status_value, status_value)
    product_name = html.escape(order.product.name if order.product else "Sản phẩm")
    created_at = order.created_at.strftime("%d/%m/%Y %H:%M") if order.created_at else "N/A"
    amount = float(order.total_amount or 0)
    payment_method = html.escape(order.payment_method or "N/A")
    payment_note = html.escape(order.payment_note or "")

    text = (
        f"🔹 <b>Đơn #{order.id}</b>\n"
        f"   Sản phẩm: {product_name}\n"
        f"   Tổng tiền: {amount:,.0f}đ\n"
        f"   Ngày tạo: {created_at}\n"
        f"   Trạng thái: {status_text}\n"
        f"   Phương thức: {payment_method}\n"
    )
    if payment_note:
        text += f"   Ghi chú: {payment_note}\n"
    return text + "\n"


async def _get_recent_orders(user_id: int) -> list[Order]:
    async with async_session() as session:
        result = await session.execute(
            select(Order)
            .options(selectinload(Order.product))
            .where(Order.user_id == user_id)
            .order_by(Order.created_at.desc())
            .limit(10)
        )
        return list(result.scalars().all())


async def send_user_orders(message: types.Message) -> None:
    if not await _ensure_user_allowed(message):
        return

    orders = await _get_recent_orders(message.from_user.id)
    if not orders:
        await message.answer(
            "📦 Bạn chưa có đơn hàng nào. Bấm 🛍 Mua hàng để chọn sản phẩm đầu tiên.",
            reply_markup=get_persistent_menu_kb(),
        )
        return

    text = "📦 <b>10 đơn hàng gần nhất của bạn</b>\n\n"
    for order in orders:
        text += _format_order(order)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛍 Tiếp tục mua hàng", callback_data="shop_catalog")],
        [InlineKeyboardButton(text="💬 Hỗ trợ về đơn hàng", callback_data="order_support_latest")],
    ])
    await message.answer(text, reply_markup=keyboard)


@router.callback_query(F.data == "shop_orders")
async def show_orders(callback: types.CallbackQuery):
    async with async_session() as session:
        user = await session.get(User, callback.from_user.id)
        if user and user.is_banned:
            await callback.message.answer(
                "🚫 Tài khoản của bạn đã bị cấm sử dụng bot.",
                reply_markup=get_persistent_menu_kb(),
            )
            await callback.answer()
            return

    orders = await _get_recent_orders(callback.from_user.id)
    if not orders:
        await callback.message.answer("Bạn chưa có đơn hàng nào.")
        await callback.answer()
        return

    text = "📦 <b>10 đơn hàng gần nhất của bạn</b>\n\n"
    for order in orders:
        text += _format_order(order)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Trở lại mua sắm", callback_data="shop_catalog")],
        [InlineKeyboardButton(text="💬 Hỗ trợ về đơn gần nhất", callback_data="order_support_latest")],
    ])

    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "order_support_latest")
async def order_support_latest(callback: types.CallbackQuery):
    orders = await _get_recent_orders(callback.from_user.id)
    latest = orders[0] if orders else None
    support_username = (settings.SHOP_SUPPORT_USERNAME or "").strip().lstrip("@")
    if not latest:
        await callback.answer("Bạn chưa có đơn hàng nào để hỗ trợ.", show_alert=True)
        return

    message = (
        "💬 <b>Hỗ trợ về đơn hàng</b>\n\n"
        f"Mã đơn: <code>#{latest.id}</code>\n"
        f"Sản phẩm: <b>{html.escape(latest.product.name if latest.product else 'Sản phẩm')}</b>\n"
        f"Trạng thái: <b>{STATUS_TEXT.get(latest.status.value, latest.status.value)}</b>\n"
        f"Phương thức thanh toán: <b>{html.escape(latest.payment_method or 'N/A')}</b>\n\n"
        "Khi nhắn cho shop, hãy gửi kèm mã đơn này để được kiểm tra nhanh hơn."
    )
    if support_username:
        message += f"\n\nLiên hệ trực tiếp: https://t.me/{support_username}"
    await callback.message.answer(message, reply_markup=get_persistent_menu_kb())
    await callback.answer()
