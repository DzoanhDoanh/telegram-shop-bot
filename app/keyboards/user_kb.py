from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)
from app.config import settings

BTN_SHOP = "🛍 Mua hàng"
BTN_WALLET = "💰 Ví của tôi"
BTN_SEARCH = "🔎 Tìm kiếm"
BTN_ORDERS = "📦 Đơn hàng của tôi"
BTN_SUPPORT = "💬 Hỗ trợ"
BTN_TERMS = "📜 Điều khoản"
BTN_HIDE_MENU = "🙈 Ẩn menu"
BTN_SHOW_MENU = "🙉 Hiện menu"
BTN_HELP = "❓ Hướng dẫn"


def get_persistent_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text=BTN_SHOP),
                KeyboardButton(text=BTN_WALLET),
            ],
            [
                KeyboardButton(text=BTN_SEARCH),
                KeyboardButton(text=BTN_ORDERS),
            ],
            [
                KeyboardButton(text=BTN_SUPPORT),
                KeyboardButton(text=BTN_TERMS),
            ],
            [
                KeyboardButton(text=BTN_HELP),
                KeyboardButton(text=BTN_HIDE_MENU),
            ],
        ],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Chọn thao tác bên dưới...",
    )


def get_show_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BTN_SHOW_MENU)]],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Bấm để hiện lại menu...",
    )


def get_main_menu_kb() -> InlineKeyboardMarkup:
    support_username = (settings.SHOP_SUPPORT_USERNAME or "").strip().lstrip("@")
    inline_keyboard = [
        [
            InlineKeyboardButton(text="🛍 Xem sản phẩm", callback_data="shop_catalog"),
            InlineKeyboardButton(text="💰 Ví của tôi", callback_data="wallet_home"),
        ],
        [
            InlineKeyboardButton(text="📦 Đơn hàng của tôi", callback_data="shop_orders"),
        ],
    ]
    if support_username:
        inline_keyboard.append([
            InlineKeyboardButton(text="💬 Hỗ trợ", url=f"https://t.me/{support_username}"),
        ])
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
