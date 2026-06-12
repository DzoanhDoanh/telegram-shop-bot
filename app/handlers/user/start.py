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
from app.handlers.user.orders import send_user_orders
from app.keyboards.user_kb import (
    BTN_HELP,
    BTN_HIDE_MENU,
    BTN_ORDERS,
    BTN_SHOP,
    BTN_SHOW_MENU,
    BTN_SUPPORT,
    BTN_TERMS,
    DEMO_SPIN_REWARDS,
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
            await message.answer(
                "🚫 Tài khoản của bạn đã bị cấm sử dụng bot.",
                reply_markup=get_persistent_menu_kb(),
            )
            return False

    return True


async def send_welcome(message: types.Message) -> None:
    await message.answer(
        f"Xin chào {message.from_user.full_name}! 👋\n\n"
        f"Chào mừng bạn đến với <b>{settings.SHOP_NAME}</b>.\n"
        "Shop bán sản phẩm số theo mô hình <b>ví điện tử trước, giao hàng tự động sau</b>.\n\n"
        "Luồng nhanh nhất: <b>Nạp ví → đợi hệ thống cộng tiền → chọn sản phẩm → bot giao hàng tự động ngay trong Telegram</b>.\n\n"
        "Bấm 🛍 Mua hàng để xem danh mục, hoặc ❓ Hướng dẫn nếu đây là lần đầu bạn mua.",
        reply_markup=get_persistent_menu_kb(),
    )


async def send_help(message: types.Message) -> None:
    if not await ensure_user(message):
        return

    await message.answer(
        "❓ <b>Hướng dẫn mua hàng</b>\n\n"
        "1. Vào <b>💰 Ví của tôi</b> và tạo yêu cầu nạp ví.\n"
        "2. Chuyển khoản <b>đúng số tiền</b> và <b>đúng mã nạp</b> mà bot đã tạo.\n"
        "3. Hệ thống sẽ tự kiểm tra webhook ngân hàng và cộng số dư ví cho bạn.\n"
        "4. Sau khi ví đã có tiền, chọn sản phẩm cần mua và xác nhận thanh toán.\n"
        "5. Bot sẽ tự giao sản phẩm số ngay trong Telegram nếu đơn thành công.\n\n"
        "Nếu chuyển khoản sai nội dung, webhook chậm, hoặc có lỗi ngoại lệ, hãy bấm 💬 Hỗ trợ. Gửi bill thủ công chỉ là phương án fallback khi cần shop kiểm tra.\n\n"
        "Bạn có thể gõ <code>/terms</code> để xem điều khoản mua hàng và chính sách hỗ trợ.",
        reply_markup=get_persistent_menu_kb(),
    )


async def send_terms(message: types.Message) -> None:
    if not await ensure_user(message):
        return

    await message.answer(
        "📜 <b>Điều khoản mua hàng</b>\n\n"
        "1. Shop cung cấp <b>sản phẩm số</b>, phần lớn được giao tự động ngay trong Telegram sau khi thanh toán thành công.\n"
        "2. Người mua phải chuyển khoản <b>đúng số tiền</b> và <b>đúng mã nạp</b> mà bot cung cấp. Chuyển sai nội dung vui lòng liên hệ shop để được hỗ trợ.\n"
        "3. Sau khi thanh toán thành công, bot sẽ giao đúng nội dung sản phẩm tương ứng ngay trong Telegram.\n"
        "4. Sau khi sản phẩm số đã giao thành công, shop chỉ hỗ trợ các lỗi hợp lệ như giao thiếu, giao sai, hoặc sự cố hệ thống có thể xác minh.\n"
        "5. Shop <b>không hoàn tiền tùy ý</b> đối với các trường hợp người dùng đổi ý sau khi đã nhận đúng sản phẩm số, trừ khi admin xác nhận có lỗi từ hệ thống hoặc từ phía shop.\n"
        "6. Nếu cần hỗ trợ, hãy bấm <b>💬 Hỗ trợ</b> hoặc gõ <code>/support</code> và gửi kèm mã đơn hàng nếu có.\n"
        "7. Shop có quyền từ chối phục vụ hoặc khóa tài khoản đối với hành vi gian lận, lạm dụng, spam hoặc cố tình gây rối hệ thống.",
        reply_markup=get_persistent_menu_kb(),
    )


async def send_support(message: types.Message, state: FSMContext) -> None:
    if not await ensure_user(message):
        return

    await state.set_state(SupportState.waiting_for_message)
    support_username = (settings.SHOP_SUPPORT_USERNAME or "").strip().lstrip("@")
    extra_line = (
        f"Nếu cần, bạn cũng có thể nhắn trực tiếp tại: https://t.me/{support_username}\n\n"
        if support_username else ""
    )
    await message.answer(
        "💬 <b>Hỗ trợ khách hàng</b>\n\n"
        "Hãy gửi nội dung bạn cần hỗ trợ ở tin nhắn tiếp theo.\n"
        "Nếu liên quan đến đơn hàng, vui lòng ghi kèm mã đơn hàng để shop kiểm tra nhanh hơn.\n\n"
        f"{extra_line}"
        "Gõ <code>/cancel</code> nếu muốn hủy.",
        reply_markup=get_persistent_menu_kb(),
    )


async def send_lucky_spin(message: types.Message) -> None:
    if not await ensure_user(message):
        return

    rewards_preview = "\n".join(f"• {reward}" for reward in DEMO_SPIN_REWARDS)
    await message.answer(
        "🎡 <b>Vòng quay may mắn</b>\n\n"
        "Thử vận may của bạn với một vòng quay vui vẻ ngay trong bot.\n"
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
    await message.answer("Đã hiện lại menu phím bấm bên dưới.", reply_markup=get_persistent_menu_kb())


@router.message(Command("cancel"), SupportState.waiting_for_message)
async def cancel_support(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Đã hủy gửi yêu cầu hỗ trợ.", reply_markup=get_persistent_menu_kb())


@router.message(SupportState.waiting_for_message)
async def process_support_message(message: types.Message, state: FSMContext):
    if not await ensure_user(message):
        await state.clear()
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
            "Hiện shop chưa nhận được yêu cầu hỗ trợ tự động. Vui lòng thử lại sau hoặc liên hệ admin trực tiếp.",
            reply_markup=get_persistent_menu_kb(),
        )
        return

    await message.answer(
        "✅ Shop đã nhận được yêu cầu hỗ trợ của bạn.\n"
        "Admin sẽ phản hồi sớm nhất có thể ngay trong bot này.",
        reply_markup=get_persistent_menu_kb(),
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


@router.callback_query(F.data == "lucky_spin_demo")
async def lucky_spin_demo(callback: types.CallbackQuery):
    if not callback.message:
        await callback.answer("Không thể thực hiện vòng quay lúc này.", show_alert=True)
        return
    if not await ensure_user(callback.message):
        await callback.answer()
        return

    reward = random.choice(DEMO_SPIN_REWARDS)
    await callback.answer("Vòng quay đã dừng!", show_alert=False)
    await callback.message.answer(
        "🎉 <b>Kết quả vòng quay may mắn</b>\n\n"
        f"Bạn quay trúng: <b>{html_decoration.quote(reward)}</b>\n\n"
        "Không có thưởng thật đâu. Lêu lêu.",
        reply_markup=get_lucky_spin_kb(),
    )
