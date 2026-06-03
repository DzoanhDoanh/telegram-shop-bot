from aiogram import Router, F, types
from aiogram.filters import Command
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.session import async_session
from app.database.models import Order, OrderStatus
from app.config import settings

router = Router()

async def get_stats_text(session: AsyncSession) -> str:
    # Tổng đơn hàng
    total_orders = await session.scalar(select(func.count(Order.id)))
    # Tổng đơn hoàn thành
    completed_orders = await session.scalar(select(func.count(Order.id)).where(Order.status == OrderStatus.COMPLETED))
    # Tổng doanh thu
    revenue = await session.scalar(select(func.sum(Order.total_amount)).where(Order.status == OrderStatus.COMPLETED)) or 0
    # Chờ duyệt
    pending = await session.scalar(select(func.count(Order.id)).where(Order.status == OrderStatus.PENDING_PAYMENT))
    
    return (
        f"📊 <b>THỐNG KÊ DOANH THU</b>\n\n"
        f"🔹 <b>Tổng số đơn hàng:</b> {total_orders or 0}\n"
        f"✅ <b>Đơn hoàn thành:</b> {completed_orders or 0}\n"
        f"⏳ <b>Đơn chờ duyệt:</b> {pending or 0}\n\n"
        f"💰 <b>Tổng doanh thu:</b> {revenue:,.0f}đ"
    )

@router.message(Command("stats"))
async def cmd_stats(message: types.Message):
    if message.from_user.id not in settings.ADMIN_IDS:
        return
        
    async with async_session() as session:
        text = await get_stats_text(session)
        
    await message.answer(text)

@router.callback_query(F.data == "admin_stats")
async def cb_stats(callback: types.CallbackQuery):
    if callback.from_user.id not in settings.ADMIN_IDS:
        return
        
    async with async_session() as session:
        text = await get_stats_text(session)
        
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Trở lại", callback_data="admin_dashboard")]
    ])
    
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()

@router.callback_query(F.data == "admin_dashboard")
async def back_to_dashboard(callback: types.CallbackQuery):
    if callback.from_user.id not in settings.ADMIN_IDS:
        return
        
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Thống kê", callback_data="admin_stats")]
    ])
    
    await callback.message.edit_text(
        "🛠 <b>Admin Dashboard</b>\n\n"
        "Chào mừng bạn đến với khu vực quản trị. Vui lòng chọn chức năng bên dưới:",
        reply_markup=kb
    )
    await callback.answer()
