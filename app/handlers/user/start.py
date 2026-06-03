from aiogram import F, Router, types
from aiogram.filters import Command, CommandStart

from app.config import settings
from app.database.models import User
from app.database.session import async_session
from app.handlers.user.catalog import send_catalog
from app.handlers.user.orders import send_user_orders
from app.keyboards.user_kb import (
    BTN_HELP,
    BTN_ORDERS,
    BTN_SHOP,
    BTN_SUPPORT,
    get_persistent_menu_kb,
)

router = Router()


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
        "Nếu chuyển khoản sai nội dung, webhook chậm, hoặc có lỗi ngoại lệ, hãy bấm 💬 Hỗ trợ. Gửi bill thủ công chỉ là phương án fallback khi cần shop kiểm tra.",
        reply_markup=get_persistent_menu_kb(),
    )


async def send_support(message: types.Message) -> None:
    if not await ensure_user(message):
        return

    support_username = (settings.SHOP_SUPPORT_USERNAME or "").strip().lstrip("@")
    if support_username:
        await message.answer(
            "💬 <b>Hỗ trợ khách hàng</b>\n\n"
            f"Bạn có thể nhắn trực tiếp cho shop tại: https://t.me/{support_username}\n\n"
            "Vui lòng gửi mã đơn hàng nếu cần hỗ trợ về thanh toán hoặc giao hàng.",
            reply_markup=get_persistent_menu_kb(),
        )
        return

    await message.answer(
        "💬 <b>Hỗ trợ khách hàng</b>\n\n"
        "Vui lòng trả lời tin nhắn này và mô tả vấn đề bạn gặp phải. "
        "Nếu liên quan đến đơn hàng, hãy gửi kèm mã đơn để shop kiểm tra nhanh hơn.",
        reply_markup=get_persistent_menu_kb(),
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


@router.message(Command("support"))
@router.message(F.text == BTN_SUPPORT)
async def cmd_support(message: types.Message):
    await send_support(message)


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
