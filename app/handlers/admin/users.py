from aiogram import Router, types
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.text_decorations import html_decoration
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database.session import async_session
from app.database.models import User
from app.config import settings
from app.web.audit import write_bot_admin_audit

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

    write_bot_admin_audit(message.from_user.id, "telegram_admin_ban", target_id=target_id)
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

    write_bot_admin_audit(message.from_user.id, "telegram_admin_unban", target_id=target_id)
    await message.answer(f"✅ Đã gỡ cấm người dùng {target_id} thành công!")

@router.message(Command("reply"))
async def cmd_reply(message: types.Message, command: CommandObject = None):
    if message.from_user.id not in settings.ADMIN_IDS:
        return

    if not command or not command.args:
        await message.answer(
            "⚠️ Sai cú pháp! Sử dụng: <code>/reply [user_id] [nội dung]</code>\n"
            "Ví dụ: <code>/reply 7623630839 Shop đã kiểm tra và xử lý xong cho bạn.</code>"
        )
        return

    parts = command.args.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("⚠️ Thiếu nội dung phản hồi. Sử dụng: <code>/reply [user_id] [nội dung]</code>")
        return

    try:
        target_id = int(parts[0])
    except ValueError:
        await message.answer("⚠️ User ID không hợp lệ. Vui lòng nhập số Telegram ID của người dùng.")
        return

    content = parts[1].strip()
    if not content:
        await message.answer("⚠️ Nội dung phản hồi không được để trống.")
        return

    async with async_session() as session:
        user = await session.get(User, target_id)
        if not user:
            await message.answer("❌ Người dùng không tồn tại trong hệ thống!")
            return

    outgoing_text = (
        "💬 <b>Phản hồi từ shop</b>\n\n"
        f"{html_decoration.quote(content)}"
    )

    try:
        await message.bot.send_message(chat_id=target_id, text=outgoing_text)
    except Exception:
        await message.answer(
            "❌ Không gửi được phản hồi cho người dùng này.\n"
            "Có thể họ chưa bắt đầu bot hoặc đã chặn bot."
        )
        return

    write_bot_admin_audit(message.from_user.id, "telegram_admin_reply", target_id=target_id, content_preview=content[:200])
    await message.answer(
        "✅ Đã gửi phản hồi hỗ trợ thành công.\n\n"
        f"👤 User ID: <code>{target_id}</code>\n"
        f"📝 Nội dung: {html_decoration.quote(content)}"
    )

@router.message(Command("msg"))
async def cmd_msg(message: types.Message, command: CommandObject = None):
    if message.from_user.id not in settings.ADMIN_IDS:
        return

    if not command or not command.args:
        await message.answer(
            "⚠️ Sai cú pháp! Sử dụng: <code>/msg [user_id] [nội dung]</code>\n"
            "Ví dụ: <code>/msg 7623630839 Chào bạn, shop đã xử lý đơn hàng của bạn.</code>"
        )
        return

    parts = command.args.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("⚠️ Thiếu nội dung tin nhắn. Sử dụng: <code>/msg [user_id] [nội dung]</code>")
        return

    try:
        target_id = int(parts[0])
    except ValueError:
        await message.answer("⚠️ User ID không hợp lệ. Vui lòng nhập số Telegram ID của người dùng.")
        return

    content = parts[1].strip()
    if not content:
        await message.answer("⚠️ Nội dung tin nhắn không được để trống.")
        return

    async with async_session() as session:
        user = await session.get(User, target_id)
        if not user:
            await message.answer("❌ Người dùng không tồn tại trong hệ thống!")
            return

    outgoing_text = (
        "📩 <b>Tin nhắn từ shop</b>\n\n"
        f"{html_decoration.quote(content)}"
    )

    try:
        await message.bot.send_message(chat_id=target_id, text=outgoing_text)
    except Exception:
        await message.answer(
            "❌ Không gửi được tin nhắn cho người dùng này.\n"
            "Có thể họ chưa bắt đầu bot hoặc đã chặn bot."
        )
        return

    write_bot_admin_audit(message.from_user.id, "telegram_admin_msg", target_id=target_id, content_preview=content[:200])
    await message.answer(
        "✅ Đã gửi tin nhắn thành công.\n\n"
        f"👤 User ID: <code>{target_id}</code>\n"
        f"📝 Nội dung: {html_decoration.quote(content)}"
    )

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
        
    write_bot_admin_audit(message.from_user.id, "telegram_admin_broadcast_start")
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
    write_bot_admin_audit(message.from_user.id, "telegram_admin_broadcast_done", success_count=success_count, fail_count=fail_count)
    await message.answer(
        f"✅ <b>Hoàn tất gửi thông báo!</b>\n\n"
        f"🟢 Thành công: {success_count}\n"
        f"🔴 Thất bại: {fail_count} (Có thể họ đã block bot)"
    )
