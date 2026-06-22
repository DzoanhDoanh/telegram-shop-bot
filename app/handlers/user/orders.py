import html

from aiogram import Router, F, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database.session import async_session
from app.config import settings
from app.database.models import Order, User
from app.keyboards.user_kb import get_persistent_menu_kb
from app.services import wallet_service, app_config_service, payment_policy_service
from app.services.order_code import get_order_code

router = Router()


STATUS_EMOJI = {
    "pending_payment": "⏳",
    "paid": "💸",
    "completed": "✅",
    "cancelled": "❌",
    "refunded": "🔄",
}


async def _orders_app_config():
    async with async_session() as session:
        return await app_config_service.get_app_config_view(session)


async def _ensure_user_allowed(message: types.Message) -> bool:
    async with async_session() as session:
        user = await session.get(User, message.from_user.id)
        if user and user.is_banned:
            app_config = await app_config_service.get_app_config_view(session)
            await message.answer(
                "🚫 Tài khoản của bạn đã bị cấm sử dụng bot.",
                reply_markup=get_persistent_menu_kb(app_config.show_terms_button, app_config.show_help_button),
            )
            return False
    return True


def _format_order(order: Order) -> str:
    status_value = order.status.value
    status_label = wallet_service.get_order_status_label(order.status)
    status_text = f"{STATUS_EMOJI.get(status_value, '•')} {status_label}"
    product_name = html.escape(order.product.name if order.product else "Sản phẩm")
    created_at = order.created_at.strftime("%d/%m/%Y %H:%M") if order.created_at else "Chưa rõ"
    amount = float(order.total_amount or 0)
    original_amount = float(order.original_amount or order.total_amount or 0)
    discount_amount = float(order.discount_amount or 0)
    voucher_code = html.escape(order.voucher_code or "")
    payment_method = html.escape(payment_policy_service.get_payment_method_label(order.payment_method))
    payment_note = html.escape(order.payment_note or "")
    quantity = int(order.quantity or 1)

    order_code = html.escape(get_order_code(order))

    text = (
        f"🔹 <b>Đơn {order_code}</b>\n"
        f"   Sản phẩm: {product_name}\n"
        f"   Số lượng: {quantity}\n"
        + (f"   Mã giảm giá: {voucher_code}\n   Giá gốc: {original_amount:,.0f}đ\n   Giảm giá: {discount_amount:,.0f}đ\n" if voucher_code and discount_amount > 0 else "") +
        f"   Tổng thanh toán: {amount:,.0f}đ\n"
        f"   Ngày tạo: {created_at}\n"
        f"   Trạng thái: {status_text}\n"
        f"   Thanh toán: {payment_method}\n"
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
    app_config = await _orders_app_config()
    if not orders:
        await message.answer(
            "📦 Bạn chưa có đơn hàng nào. Bấm 🛍 Mua hàng để chọn sản phẩm đầu tiên.",
            reply_markup=get_persistent_menu_kb(app_config.show_terms_button, app_config.show_help_button),
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
            app_config = await app_config_service.get_app_config_view(session)
            await callback.message.answer(
                "🚫 Tài khoản của bạn đã bị cấm sử dụng bot.",
                reply_markup=get_persistent_menu_kb(app_config.show_terms_button, app_config.show_help_button),
            )
            await callback.answer()
            return

    orders = await _get_recent_orders(callback.from_user.id)
    app_config = await _orders_app_config()
    if not orders:
        await callback.message.answer(
            "Bạn chưa có đơn hàng nào. Hãy chọn sản phẩm để bắt đầu mua sắm.",
            reply_markup=get_persistent_menu_kb(app_config.show_terms_button, app_config.show_help_button),
        )
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


def _order_support_message(order: Order, support_username: str = "") -> str:
    message = (
        "💬 <b>Hỗ trợ về đơn hàng</b>\n\n"
        f"Mã đơn: <code>{html.escape(get_order_code(order))}</code>\n"
        f"Sản phẩm: <b>{html.escape(order.product.name if order.product else 'Sản phẩm')}</b>\n"
        f"Số lượng: <b>{int(order.quantity or 1)}</b>\n"
        f"Trạng thái: <b>{wallet_service.get_order_status_label(order.status)}</b>\n"
        f"Thanh toán: <b>{html.escape(payment_policy_service.get_payment_method_label(order.payment_method))}</b>\n\n"
        "Mẫu nhắn shop:\n"
        f"<code>Shop ơi kiểm tra giúp mình đơn {html.escape(get_order_code(order))}</code>\n\n"
        "Khi nhắn cho shop, hãy gửi kèm mã đơn này để được kiểm tra nhanh hơn."
    )
    if support_username:
        message += f"\n\nLiên hệ trực tiếp: https://t.me/{support_username}"
    return message


@router.callback_query(F.data == "order_support_latest")
async def order_support_latest(callback: types.CallbackQuery):
    orders = await _get_recent_orders(callback.from_user.id)
    latest = orders[0] if orders else None
    if not latest:
        await callback.answer("Bạn chưa có đơn hàng nào để hỗ trợ.", show_alert=True)
        return

    async with async_session() as session:
        app_config = await app_config_service.get_app_config_view(session)
    await callback.message.answer(
        _order_support_message(latest, app_config.support_username),
        reply_markup=get_persistent_menu_kb(app_config.show_terms_button, app_config.show_help_button),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("order_support_"))
async def order_support_specific(callback: types.CallbackQuery):
    order_id = int(callback.data.removeprefix("order_support_"))
    async with async_session() as session:
        order = await session.scalar(
            select(Order)
            .options(selectinload(Order.product))
            .where(Order.id == order_id, Order.user_id == callback.from_user.id)
        )
        app_config = await app_config_service.get_app_config_view(session)
    if not order:
        await callback.answer("Không tìm thấy đơn hàng cần hỗ trợ.", show_alert=True)
        return
    await callback.message.answer(
        _order_support_message(order, app_config.support_username),
        reply_markup=get_persistent_menu_kb(app_config.show_terms_button, app_config.show_help_button),
    )
    await callback.answer()
