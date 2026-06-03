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
from app.services import wallet_service

router = Router()


class WalletState(StatesGroup):
    waiting_for_deposit_amount = State()


def _support_button() -> InlineKeyboardButton:
    support_username = (settings.SHOP_SUPPORT_USERNAME or "").strip().lstrip("@")
    if support_username:
        return InlineKeyboardButton(text="Cần hỗ trợ", url=f"https://t.me/{support_username}")
    return InlineKeyboardButton(text="Cần hỗ trợ", callback_data="wallet_support")


def _wallet_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Nạp tiền", callback_data="wallet_deposit")],
        [InlineKeyboardButton(text="Lịch sử ví", callback_data="wallet_history")],
        [InlineKeyboardButton(text="Mua hàng", callback_data="shop_catalog")],
        [_support_button()],
    ])


def _deposit_keyboard(tx_id: int) -> InlineKeyboardMarkup:
    keyboard = []
    keyboard.append([InlineKeyboardButton(text="Hủy yêu cầu nạp ví", callback_data=f"wallet_cancel_deposit_{tx_id}")])
    keyboard.append([InlineKeyboardButton(text="Hỗ trợ về mã nạp này", callback_data=f"wallet_support_tx_{tx_id}")])
    keyboard.append([InlineKeyboardButton(text="Xem ví", callback_data="wallet_home")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


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
            await message.answer("Tài khoản của bạn đã bị cấm sử dụng bot.", reply_markup=get_persistent_menu_kb())
            return None
        return user


async def _wallet_summary_text(user: User) -> str:
    return (
        "💰 <b>Ví của tôi</b>\n\n"
        f"Số dư hiện tại: <b>{wallet_service.format_vnd(user.wallet_balance)}</b>\n\n"
        "Luồng chính: <b>Nạp ví → hệ thống tự cộng → bấm mua → bot giao hàng tự động</b>.\n"
        "Nếu chuyển khoản sai nội dung hoặc webhook ngân hàng chậm, bạn vẫn có thể bấm hỗ trợ để shop kiểm tra thủ công."
    )


async def send_wallet(message: types.Message) -> None:
    user = await _ensure_user(message)
    if not user:
        return
    await message.answer(
        await _wallet_summary_text(user),
        reply_markup=_wallet_keyboard(),
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
    labels = {
        "deposit": "Nạp ví",
        "purchase": "Mua hàng",
        "refund": "Hoàn tiền",
        "admin_credit": "Admin cộng",
        "admin_debit": "Admin trừ",
    }
    for tx in transactions:
        when = tx.created_at.strftime("%d/%m %H:%M") if tx.created_at else "N/A"
        lines.append(
            f"• #{tx.id} | {labels.get(tx.tx_type.value, tx.tx_type.value)} | {wallet_service.format_vnd(tx.amount)} | {tx.status.value} | {when}"
        )
        if tx.reference:
            lines.append(f"  Mã: <code>{html.escape(tx.reference)}</code>")
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
    await callback.message.edit_text(
        await _wallet_summary_text(user),
        reply_markup=_wallet_keyboard(),
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


def _support_text_for_deposit(tx: wallet_service.WalletTransaction | None) -> str:
    base = (
        "🆘 <b>Hỗ trợ nạp ví</b>\n\n"
        "Nếu bạn đã chuyển khoản nhưng ví chưa cộng, hãy gửi cho shop:\n"
        "1. Mã nạp ví.\n"
        "2. Số tiền đã chuyển.\n"
        "3. Ảnh bill hoặc mã giao dịch ngân hàng.\n\n"
    )
    if not tx:
        return base + "Shop sẽ kiểm tra giao dịch và xử lý thủ công nếu webhook ngân hàng bị chậm hoặc nội dung chuyển khoản sai."
    return (
        base
        + f"Mã nạp hiện tại: <code>{tx.reference or 'N/A'}</code>\n"
        + f"Số tiền yêu cầu: <b>{wallet_service.format_vnd(tx.amount)}</b>\n"
        + f"Trạng thái hiện tại: <b>{tx.status.value}</b>\n\n"
        + "Hãy chụp màn hình hoặc chuyển tiếp nội dung này cho shop để kiểm tra nhanh hơn."
    )


@router.callback_query(F.data == "wallet_support")
async def wallet_support(callback: types.CallbackQuery):
    await callback.message.answer(
        _support_text_for_deposit(None),
        reply_markup=get_persistent_menu_kb(),
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
    await callback.message.answer(_support_text_for_deposit(tx), reply_markup=get_persistent_menu_kb())
    await callback.answer()


@router.callback_query(F.data == "wallet_deposit")
async def wallet_deposit(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(WalletState.waiting_for_deposit_amount)
    await callback.message.answer(
        "Nhập số tiền muốn nạp vào ví.\n\n"
        "Ví dụ: <code>50000</code>",
        reply_markup=get_persistent_menu_kb(),
    )
    await callback.answer()


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


@router.message(WalletState.waiting_for_deposit_amount)
async def process_deposit_amount(message: types.Message, state: FSMContext):
    raw_amount = (message.text or "").replace(".", "").replace(",", "").strip()
    try:
        amount = Decimal(raw_amount)
    except (InvalidOperation, ValueError):
        await message.answer("Số tiền không hợp lệ. Vui lòng nhập số, ví dụ: <code>50000</code>.")
        return

    if amount < Decimal("1000"):
        await message.answer("Số tiền nạp tối thiểu là 1,000đ.")
        return

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
            await message.answer("Tài khoản của bạn đã bị cấm sử dụng bot.", reply_markup=get_persistent_menu_kb())
            await state.clear()
            return

        payment_config = await wallet_service.get_active_payment_config(session)
        if not payment_config or not payment_config.account_no:
            await state.clear()
            await message.answer(
                "Shop chưa cấu hình tài khoản nhận tiền. Vui lòng liên hệ hỗ trợ.",
                reply_markup=get_persistent_menu_kb(),
            )
            return

        tx = await wallet_service.create_deposit_request(session, user.id, amount)
        qr_url = wallet_service.build_vietqr_url(payment_config, amount, tx.reference)

    await state.clear()

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
