from aiogram import Router, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from app.config import settings

router = Router()

@router.message(Command("admin"))
async def admin_dashboard(message: types.Message):
    if message.from_user.id not in settings.ADMIN_IDS:
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Thống kê", callback_data="admin_stats")]
    ])
    
    await message.answer(
        "🛠 <b>Admin Dashboard</b>\n\n"
        "Chào mừng bạn đến với khu vực quản trị. Vui lòng chọn chức năng bên dưới:",
        reply_markup=kb
    )
