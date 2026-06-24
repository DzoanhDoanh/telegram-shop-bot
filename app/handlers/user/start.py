from aiogram import F, Router, types
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import ReplyKeyboardRemove
from aiogram.utils.text_decorations import html_decoration
import random

from app.config import settings
from app.database.models import User
from app.database.session import async_session
from app.handlers.user.catalog import send_catalog
from app.services.app_config_service import get_app_config_view
from app.services import app_config_service, lucky_spin_service, support_service, wallet_service
from app.handlers.user.orders import send_user_orders
from app.keyboards.user_kb import (
    BTN_HELP,
    BTN_HIDE_MENU,
    BTN_ORDERS,
    BTN_SHOP,
    BTN_SHOW_MENU,
    BTN_SUPPORT,
    BTN_TERMS,
    get_lucky_spin_kb,
    get_persistent_menu_kb,
    get_show_menu_kb,
)

router = Router()


class SupportState(StatesGroup):
    waiting_for_message = State()


async def ensure_user(message: types.Message) -> bool:
    async with async_session() as session:
        user = await session.get(User, message.from_user.id)
        if not user:
            user = User(
                id=message.from_user.id,
                username=message.from_user.username,
                full_name=message.from_user.full_name,
            )
            session.add(user)
            await session.commit()

        if user.is_banned:
            async with async_session() as config_session:
                app_config = await get_app_config_view(config_session)
            await message.answer(
                "🚫 Tài khoản của bạn đã bị cấm sử dụng bot.",
                reply_markup=get_persistent_menu_kb(app_config.show_terms_button, app_config.show_help_button),
            )
            return False

    return True


async def send_welcome(message: types.Message) -> None:
    async with async_session() as session:
        app_config = await get_app_config_view(session)
    if app_config.maintenance_mode and message.from_user.id not in settings.ADMIN_IDS:
        await message.answer(
            f"{app_config.shop_display_name} đang tạm bảo trì. Vui lòng quay lại sau hoặc liên hệ hỗ trợ nếu bạn cần xử lý gấp.",
            reply_markup=get_persistent_menu_kb(app_config.show_terms_button, app_config.show_help_button),
        )
        return
    await message.answer(
        f"Xin chào {message.from_user.full_name}! 👋\n\n"
        f"Chào mừng bạn đến với <b>{app_config.shop_display_name}</b>.\n"
        f"{app_config.welcome_text}",
        reply_markup=get_persistent_menu_kb(app_config.show_terms_button, app_config.show_help_button),
    )


async def send_help(message: types.Message) -> None:
    if not await ensure_user(message):
        return

    async with async_session() as session:
        app_config = await get_app_config_view(session)

    if app_config.maintenance_mode and message.from_user.id not in settings.ADMIN_IDS:
        await message.answer(
            f"{app_config.shop_display_name} đang tạm bảo trì. Vui lòng quay lại sau hoặc nhắn hỗ trợ nếu bạn cần xử lý đơn/nạp ví đang dở.",
            reply_markup=get_persistent_menu_kb(app_config.show_terms_button, app_config.show_help_button),
        )
        return

    await message.answer(
        app_config.help_text,
        reply_markup=get_persistent_menu_kb(app_config.show_terms_button, app_config.show_help_button),
    )


async def send_terms(message: types.Message) -> None:
    if not await ensure_user(message):
        return

    async with async_session() as session:
        app_config = await get_app_config_view(session)

    support_username = app_config.support_username
    keyboard_rows = []
    if support_username:
        keyboard_rows.append([types.InlineKeyboardButton(text="Liên hệ hỗ trợ", url=f"https://t.me/{support_username}")])

    await message.answer(
        app_config.terms_text,
        reply_markup=(
            types.InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
            if keyboard_rows
            else get_persistent_menu_kb(app_config.show_terms_button, app_config.show_help_button)
        ),
    )


async def send_support(message: types.Message, state: FSMContext) -> None:
    if not await ensure_user(message):
        return

    async with async_session() as session:
        app_config = await get_app_config_view(session)
    if app_config.maintenance_mode and message.from_user.id not in settings.ADMIN_IDS:
        await message.answer(
            f"{app_config.shop_display_name} đang tạm bảo trì. Vui lòng quay lại sau.",
            reply_markup=get_persistent_menu_kb(app_config.show_terms_button, app_config.show_help_button),
        )
        return
    await state.set_state(SupportState.waiting_for_message)
    support_username = app_config.support_username
    extra_line = (
        f"Nếu cần, bạn cũng có thể nhắn trực tiếp tại: https://t.me/{support_username}\n\n"
        if support_username else ""
    )
    await message.answer(
        f"{app_config.support_text}\n\n{extra_line}Gõ <code>/cancel</code> nếu muốn hủy.",
        reply_markup=get_persistent_menu_kb(app_config.show_terms_button, app_config.show_help_button),
    )


async def send_lucky_spin(message: types.Message) -> None:
    if not await ensure_user(message):
        return

    async with async_session() as session:
        app_config = await get_app_config_view(session)
        latest_spin = await lucky_spin_service.get_latest_spin(session, message.from_user.id)
    if app_config.maintenance_mode and message.from_user.id not in settings.ADMIN_IDS:
        await message.answer(
            f"{app_config.shop_display_name} đang tạm bảo trì. Vui lòng quay lại sau.",
            reply_markup=get_persistent_menu_kb(app_config.show_terms_button, app_config.show_help_button),
        )
        return
    rewards_preview = "\n".join(f"• {reward}" for reward in lucky_spin_service.reward_preview_labels())

    cooldown_line = "Bạn đang có <b>1 lượt quay mỗi 24 giờ</b>."
    if latest_spin and latest_spin.created_at:
        cooldown_line = f"Lượt quay gần nhất: <b>{latest_spin.created_at.strftime('%H:%M %d/%m/%Y')}</b>. Mỗi user có 1 lượt quay mỗi 24 giờ."

    await message.answer(
        "🎡 <b>Vòng quay may mắn</b>\n\n"
        "Retention mini-game đã được mở ở bản cơ bản: quay mỗi ngày để nhận thưởng ví, voucher hoặc quà nhỏ từ shop.\n\n"
        f"{cooldown_line}\n\n"
        "<b>Một vài phần thưởng có thể quay trúng:</b>\n"
        f"{rewards_preview}\n\n"
        "Bấm nút bên dưới để quay ngay.",
        reply_markup=get_lucky_spin_kb(),
    )


@router.message(CommandStart())
async def cmd_start(message: types.Message):
    if not await ensure_user(message):
        return
    await send_welcome(message)


@router.message(Command("help"))
@router.message(F.text == BTN_HELP)
async def cmd_help(message: types.Message):
    await send_help(message)


@router.message(Command("terms"))
@router.message(F.text == BTN_TERMS)
async def cmd_terms(message: types.Message):
    await send_terms(message)


@router.message(Command("vongquaymayman"))
async def cmd_lucky_spin(message: types.Message):
    async with async_session() as session:
        app_config = await get_app_config_view(session)
    if not app_config.enable_lucky_spin:
        await message.answer("Tính năng vòng quay may mắn đang tạm ẩn.", reply_markup=get_persistent_menu_kb(app_config.show_terms_button, app_config.show_help_button))
        return
    await send_lucky_spin(message)


@router.message(Command("support"))
@router.message(F.text == BTN_SUPPORT)
async def cmd_support(message: types.Message, state: FSMContext):
    await send_support(message, state)


@router.message(Command("hide"))
@router.message(F.text == BTN_HIDE_MENU)
async def cmd_hide_menu(message: types.Message):
    if not await ensure_user(message):
        return
    await message.answer(
        "Đã ẩn menu phím bấm. Khi cần, bấm nút bên dưới để hiện lại menu.",
        reply_markup=ReplyKeyboardRemove(),
    )
    await message.answer("Menu đã được thu gọn.", reply_markup=get_show_menu_kb())


@router.message(Command("menu"))
@router.message(F.text == BTN_SHOW_MENU)
async def cmd_show_menu(message: types.Message):
    if not await ensure_user(message):
        return
    async with async_session() as session:
        app_config = await get_app_config_view(session)
    await message.answer(
        "Đã hiện lại menu phím bấm bên dưới.",
        reply_markup=get_persistent_menu_kb(app_config.show_terms_button, app_config.show_help_button),
    )


@router.message(Command("cancel"), SupportState.waiting_for_message)
async def cancel_support(message: types.Message, state: FSMContext):
    await state.clear()
    async with async_session() as session:
        app_config = await get_app_config_view(session)
    await message.answer(
        "Đã hủy gửi yêu cầu hỗ trợ.",
        reply_markup=get_persistent_menu_kb(app_config.show_terms_button, app_config.show_help_button),
    )


@router.message(SupportState.waiting_for_message)
async def process_support_message(message: types.Message, state: FSMContext):
    if not await ensure_user(message):
        await state.clear()
        return

    async with async_session() as session:
        app_config = await get_app_config_view(session)
    if app_config.maintenance_mode and message.from_user.id not in settings.ADMIN_IDS:
        await state.clear()
        await message.answer(
            f"{app_config.shop_display_name} đang tạm bảo trì. Vui lòng quay lại sau.",
            reply_markup=get_persistent_menu_kb(app_config.show_terms_button, app_config.show_help_button),
        )
        return

    user_id = message.from_user.id
    username = message.from_user.username or "không có"
    full_name = message.from_user.full_name or "Không rõ tên"
    support_text = (
        "🆘 <b>Yêu cầu hỗ trợ mới</b>\n\n"
        f"👤 Tên: <b>{html_decoration.quote(full_name)}</b>\n"
        f"🆔 User ID: <code>{user_id}</code>\n"
        f"🔗 Username: <code>@{html_decoration.quote(username)}</code>\n\n"
        "📝 Nội dung:\n"
        f"{html_decoration.quote(message.text or '')}\n\n"
        f"Trả lời nhanh: <code>/reply {user_id} nội_dung</code>"
    )

    if not app_config.enable_support_forwarding:
        await state.clear()
        await message.answer(
            "Tính năng hỗ trợ tạm thời đang được bảo trì. Vui lòng thử lại sau.",
            reply_markup=get_persistent_menu_kb(app_config.show_terms_button, app_config.show_help_button),
        )
        return

    async with async_session() as session:
        ticket_result = await support_service.create_or_append_user_ticket(
            session,
            user_id=user_id,
            content=message.text or '',
            telegram_message_id=message.message_id,
        )

    support_text = (
        "🆘 <b>Yêu cầu hỗ trợ mới</b>\n\n"
        f"🎫 Ticket: <code>#{ticket_result.ticket.id}</code>\n"
        f"👤 Tên: <b>{html_decoration.quote(full_name)}</b>\n"
        f"🆔 User ID: <code>{user_id}</code>\n"
        f"🔗 Username: <code>@{html_decoration.quote(username)}</code>\n\n"
        "📝 Nội dung:\n"
        f"{html_decoration.quote(message.text or '')}\n\n"
        f"Trả lời nhanh: <code>/reply {user_id} nội_dung</code>\n"
        f"Mở ticket: <code>/admin/support/{ticket_result.ticket.id}</code>"
    )

    sent = 0
    for admin_id in settings.ADMIN_IDS:
        try:
            await message.bot.send_message(chat_id=admin_id, text=support_text)
            sent += 1
        except Exception:
            continue

    await state.clear()
    if sent == 0:
        await message.answer(
            "Hiện shop chưa nhận được yêu cầu hỗ trợ tự động. Vui lòng thử lại sau hoặc liên hệ shop trực tiếp.",
            reply_markup=get_persistent_menu_kb(app_config.show_terms_button, app_config.show_help_button),
        )
        return

    await message.answer(
        f"✅ Shop đã nhận được yêu cầu hỗ trợ của bạn.\nMã ticket: <code>#{ticket_result.ticket.id}</code>\nAdmin sẽ phản hồi sớm nhất có thể ngay trong bot này.",
        reply_markup=get_persistent_menu_kb(app_config.show_terms_button, app_config.show_help_button),
    )


@router.message(Command("shop"))
@router.message(F.text == BTN_SHOP)
async def cmd_shop(message: types.Message):
    if not await ensure_user(message):
        return
    await send_catalog(message)


@router.message(Command("orders"))
@router.message(F.text == BTN_ORDERS)
async def cmd_orders(message: types.Message):
    if not await ensure_user(message):
        return
    await send_user_orders(message)


@router.callback_query(F.data == "lucky_spin_play")
async def lucky_spin_play(callback: types.CallbackQuery):
    if not callback.message:
        await callback.answer("Không thể thực hiện vòng quay lúc này.", show_alert=True)
        return
    if not await ensure_user(callback.message):
        await callback.answer()
        return

    async with async_session() as session:
        app_config = await get_app_config_view(session)
        if app_config.maintenance_mode and callback.from_user.id not in settings.ADMIN_IDS:
            await callback.message.answer(
                f"{app_config.shop_display_name} đang tạm bảo trì. Vui lòng quay lại sau.",
                reply_markup=get_persistent_menu_kb(app_config.show_terms_button, app_config.show_help_button),
            )
            await callback.answer()
            return
        outcome = await lucky_spin_service.spin_once(session, callback.from_user.id)

    if not outcome.ok:
        if outcome.next_available_at:
            await callback.answer(
                f"Bạn đã dùng lượt quay rồi. Quay lại sau {outcome.next_available_at.strftime('%H:%M %d/%m')}",
                show_alert=True,
            )
        else:
            await callback.answer(outcome.message, show_alert=True)
        return

    reward_lines = [
        "🎉 <b>Kết quả vòng quay may mắn</b>",
        "",
        f"Bạn quay trúng: <b>{html_decoration.quote(outcome.reward_label)}</b>",
    ]
    if outcome.wallet_amount > 0:
        reward_lines.append(f"Ví của bạn đã được cộng thêm: <b>{wallet_service.format_vnd(outcome.wallet_amount)}</b>")
    if outcome.voucher_code:
        reward_lines.append(f"Mã voucher của bạn: <code>{html_decoration.quote(outcome.voucher_code)}</code>")
        reward_lines.append("Voucher này có thể dùng ở bước checkout nếu còn hiệu lực.")
    reward_lines.extend([
        "",
        "Bạn sẽ có lượt quay tiếp theo sau 24 giờ.",
    ])

    await callback.answer("Vòng quay đã dừng!", show_alert=False)
    await callback.message.answer("\n".join(reward_lines), reply_markup=get_lucky_spin_kb())
