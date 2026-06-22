import html
from decimal import Decimal, InvalidOperation

from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select

from app.config import settings
from app.database.models import User
from app.database.session import async_session
from app.keyboards.user_kb import BTN_WALLET, get_persistent_menu_kb
from app.services import wallet_service, app_config_service

router = Router()


class WalletState(StatesGroup):
    waiting_for_deposit_amount = State()


DEPOSIT_PRESET_AMOUNTS = [50000, 100000, 200000, 500000]


def _support_button(support_username: str = "") -> InlineKeyboardButton:
    support_username = (support_username or "").strip().lstrip("@")
    if support_username:
        return InlineKeyboardButton(text="Cần hỗ trợ", url=f"https://t.me/{support_username}")
    return InlineKeyboardButton(text="Cần hỗ trợ", callback_data="wallet_support")


def _wallet_keyboard(support_username: str = "") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Nạp tiền", callback_data="wallet_deposit")],
        [InlineKeyboardButton(text="Lịch sử ví", callback_data="wallet_history")],
        [InlineKeyboardButton(text="Mua hàng", callback_data="shop_catalog")],
        [_support_button(support_username)],
    ])


def _deposit_keyboard(tx_id: int) -> InlineKeyboardMarkup:
    keyboard = []
    keyboard.append([InlineKeyboardButton(text="Hủy yêu cầu nạp ví", callback_data=f"wallet_cancel_deposit_{tx_id}")])
    keyboard.append([InlineKeyboardButton(text="Hỗ trợ về mã nạp này", callback_data=f"wallet_support_tx_{tx_id}")])
    keyboard.append([InlineKeyboardButton(text="Xem ví", callback_data="wallet_home")])
    keyboard.append([InlineKeyboardButton(text="Mua hàng", callback_data="shop_catalog")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def _deposit_amount_picker(min_amount: int = 0) -> InlineKeyboardMarkup:
    allowed_amounts = [amount for amount in DEPOSIT_PRESET_AMOUNTS if amount >= max(0, int(min_amount or 0))]
    rows: list[list[InlineKeyboardButton]] = []
    if allowed_amounts:
        current_row: list[InlineKeyboardButton] = []
        for amount in allowed_amounts:
            current_row.append(
                InlineKeyboardButton(
                    text=wallet_service.format_vnd(amount),
                    callback_data=f"wallet_deposit_amount_{amount}",
                )
            )
            if len(current_row) == 2:
                rows.append(current_row)
                current_row = []
        if current_row:
            rows.append(current_row)
    rows.append([InlineKeyboardButton(text="⌨️ Nhập số khác", callback_data="wallet_deposit_custom")])
    rows.append([InlineKeyboardButton(text="Xem ví", callback_data="wallet_home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _ensure_user(message: types.Message) -> User | None:
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
            await session.refresh(user)
        if user.is_banned:
            app_config = await app_config_service.get_app_config_view(session)
            await message.answer(
                "Tài khoản của bạn đã bị cấm sử dụng bot.",
                reply_markup=get_persistent_menu_kb(app_config.show_terms_button, app_config.show_help_button),
            )
            return None
        return user


async def _wallet_summary_text(user: User) -> str:
    return (
        "💰 <b>Ví của tôi</b>\n\n"
        f"Số dư hiện tại: <b>{wallet_service.format_vnd(user.wallet_balance)}</b>\n\n"
        "Cách dùng: <b>Nạp ví → chờ hệ thống cộng tiền → chọn sản phẩm → bot giao hàng tự động</b>.\n"
        "Nếu bạn đã chuyển khoản đúng nhưng ví chưa được cộng sau vài phút, hãy bấm hỗ trợ để shop kiểm tra thủ công."
    )


async def _wallet_app_config():
    async with async_session() as session:
        return await app_config_service.get_app_config_view(session)


async def _wallet_maintenance_block(message: types.Message, app_config) -> bool:
    if app_config.maintenance_mode and message.from_user.id not in settings.ADMIN_IDS:
        await message.answer(
            f"{app_config.shop_display_name} đang tạm bảo trì. Vui lòng quay lại sau hoặc nhắn hỗ trợ nếu bạn cần xử lý giao dịch đang dở.",
            reply_markup=get_persistent_menu_kb(app_config.show_terms_button, app_config.show_help_button),
        )
        return True
    return False


async def send_wallet(message: types.Message) -> None:
    user = await _ensure_user(message)
    if not user:
        return
    app_config = await _wallet_app_config()
    if await _wallet_maintenance_block(message, app_config):
        return
    await message.answer(
        await _wallet_summary_text(user),
        reply_markup=_wallet_keyboard(app_config.support_username),
    )


@router.message(Command("wallet"))
@router.message(F.text == BTN_WALLET)
async def cmd_wallet(message: types.Message):
    await send_wallet(message)


async def _recent_wallet_transactions(user_id: int, limit: int = 8):
    async with async_session() as session:
        result = await session.execute(
            select(wallet_service.WalletTransaction)
            .where(wallet_service.WalletTransaction.user_id == user_id)
            .order_by(wallet_service.WalletTransaction.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())



def _wallet_history_text(transactions: list[wallet_service.WalletTransaction]) -> str:
    if not transactions:
        return "🧾 <b>Lịch sử ví</b>\n\nBạn chưa có giao dịch ví nào."

    lines = ["🧾 <b>Lịch sử ví gần đây</b>", ""]
    for tx in transactions:
        when = tx.created_at.strftime("%d/%m %H:%M") if tx.created_at else "Chưa rõ thời gian"
        lines.append(
            f"• #{tx.id} | {wallet_service.get_wallet_tx_type_label(tx.tx_type)} | {wallet_service.format_vnd(tx.amount)} | {wallet_service.get_wallet_status_label(tx.status)} | {when}"
        )
        if tx.reference:
            lines.append(f"  Mã giao dịch: <code>{html.escape(tx.reference)}</code>")
        if tx.note:
            lines.append(f"  Ghi chú: {html.escape(tx.note)}")
    return "\n".join(lines)


@router.callback_query(F.data == "wallet_home")
async def wallet_home(callback: types.CallbackQuery):
    async with async_session() as session:
        user = await session.get(User, callback.from_user.id)
        if not user:
            user = User(
                id=callback.from_user.id,
                username=callback.from_user.username,
                full_name=callback.from_user.full_name,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
        if user.is_banned:
            await callback.answer("Tài khoản của bạn đã bị cấm sử dụng bot.", show_alert=True)
            return
    app_config = await _wallet_app_config()
    await callback.message.edit_text(
        await _wallet_summary_text(user),
        reply_markup=_wallet_keyboard(app_config.support_username),
    )
    await callback.answer()


@router.callback_query(F.data == "wallet_history")
async def wallet_history(callback: types.CallbackQuery):
    transactions = await _recent_wallet_transactions(callback.from_user.id)
    await callback.message.edit_text(
        _wallet_history_text(transactions),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Xem ví", callback_data="wallet_home")],
            [InlineKeyboardButton(text="Nạp tiền", callback_data="wallet_deposit")],
        ]),
    )
    await callback.answer()


def _support_text_for_deposit(tx: wallet_service.WalletTransaction | None, support_username: str = "") -> str:
    base = (
        "🆘 <b>Hỗ trợ nạp ví</b>\n\n"
        "Nếu bạn đã chuyển khoản nhưng ví chưa cộng, hãy gửi cho shop:\n"
        "1. Mã nạp ví.\n"
        "2. Số tiền đã chuyển.\n"
        "3. Ảnh bill hoặc mã giao dịch ngân hàng.\n\n"
    )
    tail = ""
    support_username = (support_username or "").strip().lstrip("@")
    if support_username:
        tail = f"\n\nLiên hệ trực tiếp: https://t.me/{support_username}"
    if not tx:
        return base + "Shop sẽ kiểm tra giao dịch và xử lý thủ công nếu webhook ngân hàng bị chậm hoặc nội dung chuyển khoản không khớp." + tail
    return (
        base
        + f"Mã nạp hiện tại: <code>{tx.reference or 'Chưa có mã'}</code>\n"
        + f"Số tiền yêu cầu: <b>{wallet_service.format_vnd(tx.amount)}</b>\n"
        + f"Trạng thái hiện tại: <b>{wallet_service.get_wallet_status_label(tx.status)}</b>\n\n"
        + "Hãy chụp màn hình hoặc chuyển tiếp nội dung này cho shop để kiểm tra nhanh hơn."
        + tail
    )


@router.callback_query(F.data == "wallet_support")
async def wallet_support(callback: types.CallbackQuery):
    app_config = await _wallet_app_config()
    await callback.message.answer(
        _support_text_for_deposit(None, app_config.support_username),
        reply_markup=get_persistent_menu_kb(app_config.show_terms_button, app_config.show_help_button),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("wallet_support_tx_"))
async def wallet_support_tx(callback: types.CallbackQuery):
    tx_id = int(callback.data.removeprefix("wallet_support_tx_"))
    async with async_session() as session:
        tx = await session.get(wallet_service.WalletTransaction, tx_id)
        if not tx or tx.user_id != callback.from_user.id:
            await callback.answer("Không tìm thấy mã nạp cần hỗ trợ.", show_alert=True)
            return
    app_config = await _wallet_app_config()
    await callback.message.answer(
        _support_text_for_deposit(tx, app_config.support_username),
        reply_markup=get_persistent_menu_kb(app_config.show_terms_button, app_config.show_help_button),
    )
    await callback.answer()


async def _prompt_custom_deposit_amount(message: types.Message, app_config, min_deposit_amount: int = 0) -> None:
    min_deposit_note = ""
    if min_deposit_amount > 0:
        min_deposit_note = f"\n\nMức nạp tối thiểu hiện tại: <b>{wallet_service.format_vnd(min_deposit_amount)}</b>."
    await message.answer(
        "Nhập số tiền muốn nạp vào ví.\n\n"
        "Ví dụ: <code>50000</code>"
        f"{min_deposit_note}",
        reply_markup=get_persistent_menu_kb(app_config.show_terms_button, app_config.show_help_button),
    )


@router.callback_query(F.data == "wallet_deposit")
async def wallet_deposit(callback: types.CallbackQuery, state: FSMContext):
    app_config = await _wallet_app_config()
    if app_config.maintenance_mode and callback.from_user.id not in settings.ADMIN_IDS:
        await callback.message.answer(
            f"{app_config.shop_display_name} đang tạm bảo trì. Vui lòng quay lại sau để tiếp tục nạp ví.",
            reply_markup=get_persistent_menu_kb(app_config.show_terms_button, app_config.show_help_button),
        )
        await callback.answer()
        return

    async with async_session() as session:
        payment_config = await wallet_service.get_active_payment_config(session)

    min_deposit_amount = 0
    min_deposit_note = ""
    if payment_config and payment_config.min_deposit_enabled and wallet_service.money(payment_config.min_deposit_amount) > 0:
        min_deposit_amount = int(wallet_service.money(payment_config.min_deposit_amount))
        min_deposit_note = (
            f"\n\nMức nạp tối thiểu hiện tại: <b>{wallet_service.format_vnd(payment_config.min_deposit_amount)}</b>."
        )

    await state.clear()
    await callback.message.answer(
        "💳 <b>Chọn số tiền muốn nạp</b>\n\n"
        "Bạn có thể chọn nhanh một mức phổ biến hoặc nhập số khác thủ công."
        f"{min_deposit_note}",
        reply_markup=_deposit_amount_picker(min_deposit_amount),
    )
    await callback.answer()


@router.callback_query(F.data == "wallet_deposit_custom")
async def wallet_deposit_custom(callback: types.CallbackQuery, state: FSMContext):
    app_config = await _wallet_app_config()
    await state.set_state(WalletState.waiting_for_deposit_amount)
    async with async_session() as session:
        payment_config = await wallet_service.get_active_payment_config(session)
    min_deposit_amount = 0
    if payment_config and payment_config.min_deposit_enabled and wallet_service.money(payment_config.min_deposit_amount) > 0:
        min_deposit_amount = int(wallet_service.money(payment_config.min_deposit_amount))
    await _prompt_custom_deposit_amount(callback.message, app_config, min_deposit_amount)
    await callback.answer()


@router.callback_query(F.data.startswith("wallet_deposit_amount_"))
async def wallet_deposit_preset(callback: types.CallbackQuery, state: FSMContext):
    app_config = await _wallet_app_config()
    raw_amount = callback.data.removeprefix("wallet_deposit_amount_")
    try:
        amount = Decimal(raw_amount)
    except (InvalidOperation, ValueError):
        await callback.answer("Mức nạp không hợp lệ.", show_alert=True)
        return
    await state.clear()
    await callback.answer("Đang tạo yêu cầu nạp ví...")
    await _create_deposit_request_from_amount(callback.message, callback.from_user, amount, app_config)


@router.callback_query(F.data.startswith("wallet_cancel_deposit_"))
async def wallet_cancel_deposit(callback: types.CallbackQuery):
    tx_id = int(callback.data.removeprefix("wallet_cancel_deposit_"))

    async with async_session() as session:
        result = await wallet_service.cancel_deposit_request(session, callback.from_user.id, tx_id)

    if not result.success:
        await callback.answer(result.message, show_alert=True)
        return

    if result.transaction and result.transaction.deposit_qr_message_id:
        try:
            await callback.bot.delete_message(
                chat_id=callback.from_user.id,
                message_id=result.transaction.deposit_qr_message_id,
            )
        except Exception:
            pass

    try:
        await callback.message.delete()
    except Exception:
        await callback.message.edit_text(
            "❌ <b>Yêu cầu nạp ví đã được hủy</b>\n\n"
            "Tin nhắn hướng dẫn chuyển khoản này không còn hiệu lực nữa.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Nạp lại", callback_data="wallet_deposit")],
                [InlineKeyboardButton(text="Xem ví", callback_data="wallet_home")],
            ]),
        )

    await callback.answer("Đã hủy yêu cầu nạp ví")
    await callback.message.answer(
        "❌ <b>Yêu cầu nạp ví đã được hủy</b>\n\n"
        "Bạn có thể tạo yêu cầu nạp mới bất cứ lúc nào nếu vẫn muốn nạp tiền vào ví.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Tạo yêu cầu nạp mới", callback_data="wallet_deposit")],
            [InlineKeyboardButton(text="Xem ví", callback_data="wallet_home")],
        ]),
    )


async def _create_deposit_request_from_amount(message: types.Message, from_user: types.User, amount: Decimal, app_config) -> None:
    if amount <= 0:
        await message.answer(
            "Số tiền nạp phải lớn hơn 0đ. Vui lòng nhập lại.",
            reply_markup=get_persistent_menu_kb(app_config.show_terms_button, app_config.show_help_button),
        )
        return

    async with async_session() as session:
        user = await session.get(User, from_user.id)
        if not user:
            user = User(
                id=from_user.id,
                username=from_user.username,
                full_name=from_user.full_name,
            )
            session.add(user)
            await session.commit()
        if user.is_banned:
            await message.answer(
                "Tài khoản của bạn đã bị cấm sử dụng bot.",
                reply_markup=get_persistent_menu_kb(app_config.show_terms_button, app_config.show_help_button),
            )
            return

        payment_config = await wallet_service.get_active_payment_config(session)
        if not payment_config or not payment_config.account_no:
            await message.answer(
                "Shop chưa cấu hình tài khoản nhận tiền. Vui lòng liên hệ hỗ trợ.",
                reply_markup=get_persistent_menu_kb(app_config.show_terms_button, app_config.show_help_button),
            )
            return

        min_deposit_amount = wallet_service.money(getattr(payment_config, "min_deposit_amount", 0))
        min_deposit_enabled = bool(getattr(payment_config, "min_deposit_enabled", False))
        if min_deposit_enabled and min_deposit_amount > 0 and wallet_service.money(amount) < min_deposit_amount:
            await message.answer(
                "Số tiền bạn nhập đang thấp hơn mức nạp tối thiểu.\n\n"
                f"Mức nạp tối thiểu hiện tại là <b>{wallet_service.format_vnd(min_deposit_amount)}</b>.\n"
                "Vui lòng nhập lại số tiền phù hợp.",
                reply_markup=get_persistent_menu_kb(app_config.show_terms_button, app_config.show_help_button),
            )
            return

        tx = await wallet_service.create_deposit_request(session, user.id, amount)
        qr_url = wallet_service.build_vietqr_url(payment_config, amount, tx.reference)

    bank_name = html.escape(payment_config.bank_name or "")
    account_no = html.escape(payment_config.account_no or "")
    account_name = html.escape(payment_config.account_name or "")
    text = (
        "💳 <b>Yêu cầu nạp ví đã được tạo</b>\n\n"
        f"Số tiền: <b>{wallet_service.format_vnd(amount)}</b>\n"
        f"Mã nạp: <code>{tx.reference}</code>\n\n"
        "<b>Thông tin chuyển khoản</b>\n"
        f"Ngân hàng: {bank_name}\n"
        f"Số TK: <code>{account_no}</code>\n"
        f"Tên TK: {account_name}\n"
        f"Nội dung CK bắt buộc: <code>{tx.reference}</code>\n\n"
        "Hệ thống sẽ tự cộng ví khi chuyển tiền thành công.\n"
        "Nếu đã chuyển khoản nhưng ví chưa cộng sau vài phút, bấm Cần hỗ trợ và gửi mã nạp cho shop."
    )
    deposit_message = await message.answer(text, reply_markup=_deposit_keyboard(tx.id))
    qr_message = None
    if qr_url:
        try:
            qr_message = await message.answer_photo(
                qr_url,
                caption="📷 <b>QR chuyển khoản</b>\nQuét mã này để nạp ví đúng số tiền và nội dung.",
            )
        except Exception:
            qr_message = await message.answer(
                f"🔗 QR chuyển khoản: {qr_url}",
            )

    async with async_session() as session:
        await wallet_service.save_deposit_message_ids(
            session,
            tx.id,
            deposit_message_id=deposit_message.message_id,
            deposit_qr_message_id=qr_message.message_id if qr_message else None,
        )


@router.message(WalletState.waiting_for_deposit_amount)
async def process_deposit_amount(message: types.Message, state: FSMContext):
    app_config = await _wallet_app_config()
    raw_amount = (message.text or "").replace(".", "").replace(",", "").strip()
    try:
        amount = Decimal(raw_amount)
    except (InvalidOperation, ValueError):
        await message.answer(
            "Số tiền không hợp lệ. Vui lòng nhập số, ví dụ: <code>50000</code>.",
            reply_markup=get_persistent_menu_kb(app_config.show_terms_button, app_config.show_help_button),
        )
        return

    await state.clear()
    await _create_deposit_request_from_amount(message, message.from_user, amount, app_config)
