from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from app.config import settings

router = Router()


def _admin_dashboard_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Thống kê", callback_data="admin_stats")],
        [InlineKeyboardButton(text="📖 Danh sách lệnh admin", callback_data="admin_help")],
    ])


def _admin_help_text() -> str:
    return (
        "📖 <b>Danh sách lệnh admin</b>\n\n"
        "<b>Tổng quan</b>\n"
        "• <code>/admin</code> - mở dashboard admin\n"
        "• <code>/adminhelp</code> - xem lại danh sách lệnh admin\n"
        "• <code>/stats</code> - xem thống kê nhanh\n\n"
        "<b>Người dùng</b>\n"
        "• <code>/ban user_id</code> - cấm người dùng\n"
        "• <code>/unban user_id</code> - gỡ cấm người dùng\n"
        "• <code>/msg user_id nội_dung</code> - nhắn chủ động cho user\n"
        "• <code>/reply user_id nội_dung</code> - trả lời yêu cầu hỗ trợ\n"
        "• <code>/broadcast</code> - gửi thông báo tới toàn bộ user\n\n"
        "Các lệnh này chỉ hoạt động với Telegram ID nằm trong <code>ADMIN_IDS</code> của file môi trường."
    )


@router.message(Command("admin"))
async def admin_dashboard(message: types.Message):
    if message.from_user.id not in settings.ADMIN_IDS:
        return

    await message.answer(
        "🛠 <b>Admin Dashboard</b>\n\n"
        "Chào mừng bạn đến với khu vực quản trị. Vui lòng chọn chức năng bên dưới:\n\n"
        "Nếu quên lệnh, bấm <b>Danh sách lệnh admin</b> hoặc gõ <code>/adminhelp</code>.",
        reply_markup=_admin_dashboard_keyboard()
    )


@router.message(Command("adminhelp"))
async def admin_help(message: types.Message):
    if message.from_user.id not in settings.ADMIN_IDS:
        return

    await message.answer(_admin_help_text(), reply_markup=_admin_dashboard_keyboard())


@router.callback_query(F.data == "admin_help")
async def admin_help_callback(callback: types.CallbackQuery):
    if callback.from_user.id not in settings.ADMIN_IDS:
        return

    await callback.message.edit_text(_admin_help_text(), reply_markup=_admin_dashboard_keyboard())
    await callback.answer()
