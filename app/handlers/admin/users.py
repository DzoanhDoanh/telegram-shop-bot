from aiogram import Router, types
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database.session import async_session
from app.database.models import User
from app.config import settings

router = Router()

class BroadcastState(StatesGroup):
    waiting_for_message = State()

@router.message(Command("ban"))
async def cmd_ban(message: types.Message, command: CommandObject = None):
    if message.from_user.id not in settings.ADMIN_IDS:
        return
        
    if not command or not command.args:
        await message.answer("⚠️ Sai cú pháp! Sử dụng: <code>/ban [user_id]</code>")
        return
        
    try:
        target_id = int(command.args.split()[0])
    except (ValueError, IndexError):
        return
        
    async with async_session() as session:
        user = await session.get(User, target_id)
        if not user:
            await message.answer("❌ Người dùng không tồn tại trong hệ thống!")
            return
            
        user.is_banned = True
        await session.commit()
        
    await message.answer(f"✅ Đã cấm người dùng {target_id} thành công!")

@router.message(Command("unban"))
async def cmd_unban(message: types.Message, command: CommandObject = None):
    if message.from_user.id not in settings.ADMIN_IDS:
        return
        
    if not command or not command.args:
        await message.answer("⚠️ Sai cú pháp! Sử dụng: <code>/unban [user_id]</code>")
        return
        
    try:
        target_id = int(command.args.split()[0])
    except (ValueError, IndexError):
        return
        
    async with async_session() as session:
        user = await session.get(User, target_id)
        if not user:
            await message.answer("❌ Người dùng không tồn tại trong hệ thống!")
            return
            
        user.is_banned = False
        await session.commit()
        
    await message.answer(f"✅ Đã gỡ cấm người dùng {target_id} thành công!")

@router.message(Command("broadcast"))
async def cmd_broadcast(message: types.Message, state: FSMContext):
    if message.from_user.id not in settings.ADMIN_IDS:
        return
        
    await state.set_state(BroadcastState.waiting_for_message)
    await message.answer(
        "📢 <b>GỬI THÔNG BÁO (BROADCAST)</b>\n\n"
        "Vui lòng gửi nội dung thông báo bạn muốn gửi đến tất cả người dùng.\n"
        "Bạn có thể gửi text, ảnh, video...\n"
        "(Hoặc gõ /cancel để hủy)"
    )

@router.message(BroadcastState.waiting_for_message)
async def process_broadcast(message: types.Message, state: FSMContext):
    if message.text == '/cancel':
        await state.clear()
        await message.answer("Đã hủy gửi thông báo.")
        return
        
    await message.answer("🔄 Đang gửi thông báo. Quá trình này có thể mất một lúc...")
    
    success_count = 0
    fail_count = 0
    
    async with async_session() as session:
        result = await session.execute(select(User).where(User.is_banned == False))
        users = result.scalars().all()
        
    for user in users:
        try:
            await message.copy_to(user.id)
            success_count += 1
        except Exception:
            fail_count += 1
            
    await state.clear()
    await message.answer(
        f"✅ <b>Hoàn tất gửi thông báo!</b>\n\n"
        f"🟢 Thành công: {success_count}\n"
        f"🔴 Thất bại: {fail_count} (Có thể họ đã block bot)"
    )
