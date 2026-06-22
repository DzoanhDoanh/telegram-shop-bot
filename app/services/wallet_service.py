from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from html import escape
import logging
import re
from decimal import Decimal
from typing import Any
from urllib.parse import quote_plus

from aiogram import Bot
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.models import (
    InventoryItem,
    Order,
    OrderStatus,
    PaymentConfig,
    Product,
    User,
    WalletTransaction,
    WalletTxStatus,
    WalletTxType,
)
from app.services import order_payment_service, order_service, payment_policy_service, voucher_service
from app.services.order_code import get_order_code

logger = logging.getLogger(__name__)


async def notify_admins(bot: Bot | None, text: str) -> None:
    if bot is None:
        return
    from app.config import settings

    for admin_id in settings.ADMIN_IDS:
        try:
            await bot.send_message(chat_id=admin_id, text=text)
        except Exception:
            logger.exception("Failed to send admin payment alert", extra={"admin_id": admin_id})


@dataclass(slots=True)
class WalletResult:
    success: bool
    message: str
    transaction: WalletTransaction | None = None
    order: Order | None = None


def money(value: object) -> Decimal:
    if value is None:
        return Decimal("0")
    return Decimal(str(value)).quantize(Decimal("1"))


def format_vnd(value: object) -> str:
    return f"{float(money(value)):,.0f}đ"


def get_order_status_label(status: OrderStatus | str | None) -> str:
    value = status.value if hasattr(status, "value") else str(status or "")
    labels = {
        "pending_payment": "Chờ thanh toán",
        "paid": "Đã thanh toán",
        "completed": "Hoàn thành",
        "cancelled": "Đã hủy",
        "refunded": "Đã hoàn tiền",
    }
    return labels.get(value, value or "Không xác định")


def get_wallet_tx_type_label(tx_type: WalletTxType | str | None) -> str:
    value = tx_type.value if hasattr(tx_type, "value") else str(tx_type or "")
    labels = {
        "deposit": "Nạp ví",
        "purchase": "Mua hàng",
        "refund": "Hoàn tiền",
        "admin_credit": "Admin cộng",
        "admin_debit": "Admin trừ",
    }
    return labels.get(value, value or "Khác")


def get_wallet_status_label(status: WalletTxStatus | str | None) -> str:
    value = status.value if hasattr(status, "value") else str(status or "")
    labels = {
        "pending": "Chờ xử lý",
        "success": "Thành công",
        "failed": "Thất bại",
        "cancelled": "Đã hủy",
        "underpaid": "Chuyển khoản thiếu",
        "review_required": "Cần kiểm tra thủ công",
        "unmatched": "Không khớp giao dịch",
        "late_paid": "Tiền về muộn",
    }
    return labels.get(value, value or "Không xác định")


async def get_active_payment_config(session: AsyncSession) -> PaymentConfig | None:
    return await session.scalar(
        select(PaymentConfig)
        .where(PaymentConfig.is_active == True)
        .order_by(PaymentConfig.id.desc())
        .limit(1)
    )


async def ensure_payment_config(session: AsyncSession) -> PaymentConfig:
    config = await get_active_payment_config(session)
    if config:
        return config
    config = PaymentConfig(is_active=True)
    session.add(config)
    await session.flush()
    return config


def build_deposit_reference(user_id: int, tx_id: int) -> str:
    return f"DS{user_id}T{tx_id}"


def normalize_reference_text(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", value).upper()


def extract_provider_event_id(payload: dict[str, Any]) -> str | None:
    for key in ("event_id", "eventId", "webhook_id", "webhookId", "id"):
        value = payload.get(key)
        if value:
            return str(value)
    return None


def build_vietqr_url(config: PaymentConfig, amount: object, reference: str) -> str | None:
    if not config.vietqr_bank_code or not config.account_no:
        return None

    account_name = quote_plus(config.account_name or "")
    add_info = quote_plus(reference)
    amount_value = int(money(amount))
    return (
        f"https://img.vietqr.io/image/{config.vietqr_bank_code}-{config.account_no}-compact2.png"
        f"?amount={amount_value}&addInfo={add_info}&accountName={account_name}"
    )


async def create_deposit_request(session: AsyncSession, user_id: int, amount: object) -> WalletTransaction:
    amount_value = money(amount)
    pending_result = await session.execute(
        select(WalletTransaction)
        .where(
            WalletTransaction.user_id == user_id,
            WalletTransaction.tx_type == WalletTxType.DEPOSIT,
            WalletTransaction.status == WalletTxStatus.PENDING,
        )
        .order_by(WalletTransaction.created_at.desc())
        .limit(1)
    )
    existing_pending = pending_result.scalar_one_or_none()
    if existing_pending:
        return existing_pending

    tx = WalletTransaction(
        user_id=user_id,
        tx_type=WalletTxType.DEPOSIT,
        amount=amount_value,
        status=WalletTxStatus.PENDING,
        reference="PENDING",
    )
    session.add(tx)
    await session.flush()
    tx.reference = build_deposit_reference(user_id, tx.id)
    tx.normalized_reference = normalize_reference_text(tx.reference)
    await session.commit()
    await session.refresh(tx)
    return tx


async def save_deposit_message_ids(
    session: AsyncSession,
    tx_id: int,
    deposit_message_id: int | None = None,
    deposit_qr_message_id: int | None = None,
) -> WalletTransaction | None:
    tx = await session.get(WalletTransaction, tx_id)
    if not tx:
        return None
    if deposit_message_id is not None:
        tx.deposit_message_id = deposit_message_id
    if deposit_qr_message_id is not None:
        tx.deposit_qr_message_id = deposit_qr_message_id
    await session.commit()
    await session.refresh(tx)
    return tx


async def cancel_deposit_request(
    session: AsyncSession,
    user_id: int,
    tx_id: int,
) -> WalletResult:
    result = await session.execute(
        select(WalletTransaction)
        .where(WalletTransaction.id == tx_id)
        .with_for_update()
    )
    tx = result.scalar_one_or_none()
    if not tx or tx.user_id != user_id:
        return WalletResult(False, "Không tìm thấy yêu cầu nạp ví.")
    if tx.tx_type != WalletTxType.DEPOSIT:
        return WalletResult(False, "Đây không phải yêu cầu nạp ví hợp lệ.", tx)
    if tx.status == WalletTxStatus.SUCCESS:
        return WalletResult(False, "Yêu cầu này đã nạp thành công, không thể hủy.", tx)
    if tx.status == WalletTxStatus.CANCELLED:
        return WalletResult(False, "Yêu cầu nạp ví này đã được hủy trước đó.", tx)
    if tx.status != WalletTxStatus.PENDING:
        return WalletResult(False, "Yêu cầu nạp ví này không còn ở trạng thái chờ.", tx)

    tx.status = WalletTxStatus.CANCELLED
    tx.note = "Người dùng tự hủy yêu cầu nạp ví"
    tx.completed_at = datetime.utcnow()
    await session.commit()
    await session.refresh(tx)
    return WalletResult(True, "Đã hủy yêu cầu nạp ví.", tx)


async def credit_deposit(
    session: AsyncSession,
    tx: WalletTransaction,
    provider: str,
    raw_payload: dict[str, Any] | None = None,
) -> WalletResult:
    result = await session.execute(
        select(WalletTransaction)
        .options(selectinload(WalletTransaction.user))
        .where(WalletTransaction.id == tx.id)
        .with_for_update()
    )
    locked_tx = result.scalar_one_or_none()
    if not locked_tx:
        return WalletResult(False, "Không tìm thấy giao dịch ví.")
    if locked_tx.status == WalletTxStatus.SUCCESS:
        return WalletResult(True, "Giao dịch đã được cộng trước đó.", locked_tx)
    if locked_tx.status != WalletTxStatus.PENDING or locked_tx.tx_type != WalletTxType.DEPOSIT:
        return WalletResult(False, "Giao dịch không còn ở trạng thái chờ nạp.", locked_tx)

    user = await session.get(User, locked_tx.user_id, with_for_update=True)
    if not user:
        return WalletResult(False, "Không tìm thấy người dùng.", locked_tx)

    user.wallet_balance = money(user.wallet_balance) + money(locked_tx.amount)
    locked_tx.status = WalletTxStatus.SUCCESS
    locked_tx.provider = provider
    locked_tx.raw_payload = raw_payload
    locked_tx.completed_at = datetime.utcnow()
    await session.commit()
    await session.refresh(locked_tx)
    return WalletResult(True, "Đã cộng tiền vào ví.", locked_tx)


def extract_bank_payload(payload: dict[str, Any]) -> tuple[Decimal, str, str | None, str | None]:
    amount_keys = ("amount", "transferAmount", "money", "creditAmount", "value")
    content_keys = ("content", "description", "addInfo", "transactionContent", "remark")
    transaction_keys = ("transaction_id", "transactionId", "reference", "bankTransactionId")

    amount_raw = next((payload.get(key) for key in amount_keys if payload.get(key) is not None), 0)
    content = str(next((payload.get(key) for key in content_keys if payload.get(key)), ""))
    bank_tx_id = next((str(payload.get(key)) for key in transaction_keys if payload.get(key)), None)
    provider_event_id = extract_provider_event_id(payload)
    return money(amount_raw), content, bank_tx_id, provider_event_id


def build_payment_alert_text(title: str, provider: str, amount: object, content: str, bank_tx_id: str | None, note: str) -> str:
    safe_content = escape(content[:500] or "(trống)")
    safe_note = escape(note)
    safe_provider = escape(provider or "unknown")
    safe_bank_tx = escape(bank_tx_id or "unknown")
    return (
        f"{title}\n\n"
        f"Nhà cung cấp: <b>{safe_provider}</b>\n"
        f"Số tiền nhận: <b>{format_vnd(amount)}</b>\n"
        f"Mã giao dịch ngân hàng: <code>{safe_bank_tx}</code>\n"
        f"Nội dung chuyển khoản: <code>{safe_content}</code>\n"
        f"Ghi chú: {safe_note}"
    )


async def _process_direct_bank_order_webhook(
    session: AsyncSession,
    provider: str,
    payload: dict[str, Any],
    amount,
    content: str,
    normalized_content: str,
    bank_tx_id: str | None,
    provider_event_id: str | None,
    bot: Bot | None = None,
) -> WalletResult | None:
    order = await session.scalar(
        select(Order)
        .options(selectinload(Order.product), selectinload(Order.user))
        .where(
            Order.payment_method == payment_policy_service.PAYMENT_METHOD_DIRECT_BANK,
            Order.bank_transfer_reference_normalized.is_not(None),
            Order.bank_transfer_reference_normalized == normalized_content,
        )
        .limit(1)
    )
    if not order:
        return None
    if order.status == OrderStatus.COMPLETED:
        return WalletResult(True, "Đơn chuyển khoản đã được xử lý trước đó.", order=order)
    if order.status not in {OrderStatus.PENDING_PAYMENT, OrderStatus.PAID}:
        return WalletResult(False, "Đơn chuyển khoản không còn ở trạng thái chờ xử lý.", order=order)
    if amount < money(order.total_amount):
        order.payment_note = f"Chuyển khoản thiếu: nhận {format_vnd(amount)}, cần {format_vnd(order.total_amount)}"
        await session.commit()
        await session.refresh(order)
        return WalletResult(False, order.payment_note, order=order)
    if amount > money(order.total_amount):
        order.payment_note = f"Chuyển khoản thừa: nhận {format_vnd(amount)}, cần {format_vnd(order.total_amount)}. Cần review thủ công."
        await session.commit()
        await session.refresh(order)
        await notify_admins(
            bot,
            build_payment_alert_text(
                "⚠️ <b>Đơn direct bank nhận thừa tiền</b>",
                provider,
                amount,
                content,
                bank_tx_id,
                order.payment_note,
            ),
        )
        return WalletResult(False, order.payment_note, order=order)
    if not bot:
        return WalletResult(False, "Bot chưa sẵn sàng để giao đơn direct bank.", order=order)

    paid_result = await order_payment_service.mark_order_paid(
        session=session,
        order=order,
        payment_method=payment_policy_service.PAYMENT_METHOD_DIRECT_BANK,
        payment_note=f"Webhook {provider}: matched {bank_tx_id or provider_event_id or 'unknown'}",
    )
    if not paid_result.success:
        return WalletResult(False, paid_result.message, order=order)
    complete_result = await order_payment_service.complete_paid_order(session, bot, order)
    if not complete_result.success:
        return WalletResult(False, complete_result.message, order=order)
    await session.refresh(order)
    return WalletResult(True, "Đã xác nhận và giao đơn chuyển khoản trực tiếp.", order=order)


async def process_bank_webhook(
    session: AsyncSession,
    provider: str,
    payload: dict[str, Any],
    bot: Bot | None = None,
) -> WalletResult:
    amount, content, bank_tx_id, provider_event_id = extract_bank_payload(payload)
    normalized_content = normalize_reference_text(content)

    direct_bank_result = await _process_direct_bank_order_webhook(
        session=session,
        provider=provider,
        payload=payload,
        amount=amount,
        content=content,
        normalized_content=normalized_content,
        bank_tx_id=bank_tx_id,
        provider_event_id=provider_event_id,
        bot=bot,
    )
    if direct_bank_result is not None:
        return direct_bank_result

    duplicate_result = await session.execute(
        select(WalletTransaction)
        .where(
            WalletTransaction.tx_type == WalletTxType.DEPOSIT,
            or_(
                and_(WalletTransaction.provider_tx_id.is_not(None), WalletTransaction.provider_tx_id == bank_tx_id),
                and_(WalletTransaction.provider_event_id.is_not(None), WalletTransaction.provider_event_id == provider_event_id),
            ),
        )
        .order_by(WalletTransaction.created_at.desc())
        .limit(1)
    )
    duplicate_tx = duplicate_result.scalar_one_or_none()
    if duplicate_tx and duplicate_tx.status == WalletTxStatus.SUCCESS:
        return WalletResult(True, "Webhook đã xử lý trước đó, bỏ qua để tránh cộng trùng.", duplicate_tx)

    tx = await session.scalar(
        select(WalletTransaction)
        .where(
            WalletTransaction.tx_type == WalletTxType.DEPOSIT,
            WalletTransaction.normalized_reference.is_not(None),
            WalletTransaction.normalized_reference == normalized_content,
        )
        .limit(1)
    )
    if not tx:
        await notify_admins(
            bot,
            build_payment_alert_text(
                "⚠️ <b>Webhook không khớp mã nạp hoặc mã đơn</b>",
                provider,
                amount,
                content,
                bank_tx_id,
                "Không tìm thấy mã nạp ví hoặc mã đơn direct bank khớp với nội dung chuyển khoản.",
            ),
        )
        return WalletResult(False, "Không tìm thấy mã nạp ví hoặc mã đơn khớp với nội dung chuyển khoản.")
    if tx.status == WalletTxStatus.SUCCESS:
        return WalletResult(True, "Webhook đã xử lý trước đó, bỏ qua để tránh cộng trùng.", tx)
    if tx.status == WalletTxStatus.CANCELLED:
        tx.status = WalletTxStatus.LATE_PAID
        tx.provider = provider
        tx.provider_tx_id = bank_tx_id
        tx.provider_event_id = provider_event_id
        tx.raw_payload = payload
        tx.completed_at = datetime.utcnow()
        tx.note = "Tiền về sau khi yêu cầu nạp ví đã bị hủy, cần review thủ công"
        await session.commit()
        await session.refresh(tx)
        await notify_admins(
            bot,
            build_payment_alert_text(
                "⚠️ <b>Tiền về sau khi yêu cầu đã hủy</b>",
                provider,
                amount,
                content,
                bank_tx_id,
                tx.note,
            ),
        )
        return WalletResult(False, tx.note, tx)
    if tx.status != WalletTxStatus.PENDING:
        return WalletResult(False, "Giao dịch không còn ở trạng thái chờ nạp.", tx)

    tx.provider = provider
    tx.provider_tx_id = bank_tx_id
    tx.provider_event_id = provider_event_id
    tx.raw_payload = payload

    if amount < money(tx.amount):
        tx.status = WalletTxStatus.UNDERPAID
        tx.completed_at = datetime.utcnow()
        tx.note = f"Số tiền nhận {format_vnd(amount)} nhỏ hơn yêu cầu {format_vnd(tx.amount)}"
        await session.commit()
        await session.refresh(tx)
        await notify_admins(
            bot,
            build_payment_alert_text(
                "⚠️ <b>Chuyển khoản thiếu</b>",
                provider,
                amount,
                content,
                bank_tx_id,
                tx.note,
            ),
        )
        return WalletResult(False, tx.note, tx)

    if amount > money(tx.amount):
        tx.status = WalletTxStatus.REVIEW_REQUIRED
        tx.completed_at = datetime.utcnow()
        tx.note = f"Nhận thừa {format_vnd(amount)} so với yêu cầu {format_vnd(tx.amount)}, cần review thủ công"
        await session.commit()
        await session.refresh(tx)
        await notify_admins(
            bot,
            build_payment_alert_text(
                "⚠️ <b>Chuyển khoản thừa</b>",
                provider,
                amount,
                content,
                bank_tx_id,
                tx.note,
            ),
        )
        return WalletResult(False, tx.note, tx)

    tx.note = f"Matched bank transaction {bank_tx_id or 'unknown'}"
    credit_result = await credit_deposit(session, tx, provider, payload)
    if credit_result.success and credit_result.transaction:
        credit_result.transaction.provider_tx_id = bank_tx_id
        credit_result.transaction.provider_event_id = provider_event_id
        credit_result.transaction.provider = provider
        credit_result.transaction.raw_payload = payload
        await session.commit()
    if credit_result.success and bot:
        try:
            if tx.deposit_message_id:
                try:
                    await bot.delete_message(chat_id=tx.user_id, message_id=tx.deposit_message_id)
                except Exception:
                    logger.exception("Failed to delete deposit message", extra={"user_id": tx.user_id, "tx_id": tx.id, "message_id": tx.deposit_message_id})
            if tx.deposit_qr_message_id:
                try:
                    await bot.delete_message(chat_id=tx.user_id, message_id=tx.deposit_qr_message_id)
                except Exception:
                    logger.exception("Failed to delete deposit QR message", extra={"user_id": tx.user_id, "tx_id": tx.id, "message_id": tx.deposit_qr_message_id})
            await bot.send_message(
                chat_id=tx.user_id,
                text=(
                    "✅ <b>Nạp tiền thành công</b>\n\n"
                    f"Số tiền: <b>{format_vnd(tx.amount)}</b>\n"
                    f"Mã nạp: <code>{tx.reference}</code>\n"
                    f"Số dư ví đã được cập nhật."
                ),
            )
        except Exception:
            logger.exception("Failed to send deposit success notification", extra={"user_id": tx.user_id, "tx_id": tx.id})
    return credit_result


async def cancel_wallet_transaction_admin(
    session: AsyncSession,
    tx_id: int,
    actor: str,
    reason: str,
) -> WalletResult:
    result = await session.execute(
        select(WalletTransaction)
        .where(WalletTransaction.id == tx_id)
        .with_for_update()
    )
    tx = result.scalar_one_or_none()
    if not tx or tx.status != WalletTxStatus.PENDING:
        return WalletResult(False, "Không thể hủy giao dịch này.")

    tx.status = WalletTxStatus.CANCELLED
    tx.completed_at = datetime.utcnow()
    tx.note = reason.strip() or "Admin hủy giao dịch pending"
    tx.admin_actor = actor
    await session.commit()
    await session.refresh(tx)
    return WalletResult(True, "Đã hủy giao dịch pending.", tx)


async def adjust_wallet_balance(
    session: AsyncSession,
    user_id: int,
    amount: object,
    tx_type: WalletTxType,
    actor: str,
    reason: str,
) -> WalletResult:
    amount_value = money(amount)
    if amount_value <= 0:
        return WalletResult(False, "Số tiền phải lớn hơn 0.")
    if not reason.strip():
        return WalletResult(False, "Phải nhập lý do cho thao tác tài chính.")

    user = await session.get(User, user_id, with_for_update=True)
    if not user:
        return WalletResult(False, "Không tìm thấy người dùng.")

    if tx_type in {WalletTxType.ADMIN_DEBIT, WalletTxType.PURCHASE} and money(user.wallet_balance) < amount_value:
        return WalletResult(False, "Số dư ví hiện tại không đủ để trừ.")

    if tx_type in {WalletTxType.REFUND, WalletTxType.ADMIN_CREDIT}:
        user.wallet_balance = money(user.wallet_balance) + amount_value
    elif tx_type == WalletTxType.ADMIN_DEBIT:
        user.wallet_balance = money(user.wallet_balance) - amount_value
    else:
        return WalletResult(False, "Loại giao dịch không hợp lệ cho admin adjustment.")

    now = datetime.utcnow()
    tx = WalletTransaction(
        user_id=user_id,
        tx_type=tx_type,
        amount=amount_value,
        status=WalletTxStatus.SUCCESS,
        reference=f"ADM{user_id}-{int(now.timestamp())}",
        provider="admin",
        note=reason.strip(),
        admin_actor=actor,
        completed_at=now,
    )
    session.add(tx)
    await session.commit()
    await session.refresh(tx)
    return WalletResult(True, "Đã cập nhật số dư ví.", tx)


async def refund_order_to_wallet(
    session: AsyncSession,
    order_id: int,
    actor: str,
    reason: str,
) -> WalletResult:
    clean_reason = reason.strip()
    if not clean_reason:
        return WalletResult(False, "Phải nhập lý do hoàn tiền.")

    order_result = await session.execute(
        select(Order)
        .options(selectinload(Order.user))
        .where(Order.id == order_id)
        .with_for_update()
    )
    order = order_result.scalar_one_or_none()
    if not order:
        return WalletResult(False, "Không tìm thấy đơn hàng.")
    if order.status == OrderStatus.REFUNDED:
        return WalletResult(False, "Đơn hàng này đã được hoàn tiền trước đó.")
    if order.status not in {OrderStatus.COMPLETED, OrderStatus.PAID}:
        return WalletResult(False, "Chỉ có thể hoàn tiền cho đơn đã thanh toán hoặc đã hoàn thành.")

    user = await session.get(User, order.user_id, with_for_update=True)
    if not user:
        return WalletResult(False, "Không tìm thấy người dùng.")

    amount_value = money(order.total_amount)
    user.wallet_balance = money(user.wallet_balance) + amount_value
    if money(user.total_spent) >= amount_value:
        user.total_spent = money(user.total_spent) - amount_value
    else:
        user.total_spent = money(0)

    now = datetime.utcnow()
    tx = WalletTransaction(
        user_id=order.user_id,
        tx_type=WalletTxType.REFUND,
        amount=amount_value,
        status=WalletTxStatus.SUCCESS,
        reference=f"RFD{order.user_id}-{order.id}-{int(now.timestamp())}",
        provider="admin",
        note=f"Hoàn tiền đơn {get_order_code(order)}: {clean_reason}",
        admin_actor=actor,
        completed_at=now,
    )
    session.add(tx)

    order.status = OrderStatus.REFUNDED
    order.completed_at = now
    existing_note = (order.payment_note or "").strip()
    refund_note = f"Hoàn tiền: {clean_reason}"
    order.payment_note = f"{existing_note}\n{refund_note}".strip() if existing_note else refund_note

    await session.commit()
    await session.refresh(tx)
    await session.refresh(order)
    return WalletResult(True, "Đã hoàn tiền đơn hàng vào ví người dùng.", tx, order)


async def pay_product_with_wallet(
    session: AsyncSession,
    bot: Bot,
    user_id: int,
    product_id: int,
    quantity: int = 1,
    voucher_code: str | None = None,
) -> WalletResult:
    user = await session.get(User, user_id, with_for_update=True)
    if not user:
        return WalletResult(False, "Không tìm thấy người dùng.")
    if user.is_banned:
        return WalletResult(False, "Tài khoản của bạn đã bị cấm sử dụng bot.")

    product = await session.get(Product, product_id)
    if not product or not product.is_active:
        return WalletResult(False, "Sản phẩm không tồn tại hoặc đã ngừng bán.")
    if not payment_policy_service.is_payment_method_allowed(product, payment_policy_service.PAYMENT_METHOD_WALLET):
        return WalletResult(False, "Sản phẩm này không hỗ trợ thanh toán bằng ví.")

    requested_quantity = max(1, int(quantity or 1))
    if product.delivery_mode == "fixed_content":
        requested_quantity = 1
    elif not product.allow_quantity_selection:
        requested_quantity = 1

    minimum = max(1, int(product.min_quantity or 1))
    maximum = max(minimum, int(product.max_quantity or minimum))
    if product.delivery_mode != "fixed_content":
        if requested_quantity < minimum:
            return WalletResult(False, f"Số lượng tối thiểu cho sản phẩm này là {minimum}.")
        if requested_quantity > maximum:
            return WalletResult(False, f"Số lượng tối đa cho sản phẩm này là {maximum}.")

    items: list[InventoryItem] = []
    delivered_lines = ""
    if product.delivery_mode == "fixed_content":
        if not (product.fixed_delivery_content or "").strip():
            return WalletResult(False, "Sản phẩm này chưa được cấu hình nội dung giao cho khách.")
        delivered_lines = escape(product.fixed_delivery_content.strip())
    else:
        stock_result = await session.execute(
            select(InventoryItem)
            .where(
                InventoryItem.product_id == product_id,
                InventoryItem.is_sold == False,
            )
            .order_by(InventoryItem.id.asc())
            .limit(requested_quantity)
            .with_for_update(skip_locked=True)
        )
        items = list(stock_result.scalars().all())
        if len(items) < requested_quantity:
            return WalletResult(False, f"Không đủ hàng trong kho. Cần {requested_quantity}, còn {len(items)}.")
        delivered_lines = "\n".join(
            f"{index}. <code>{escape(item.content)}</code>" for index, item in enumerate(items, 1)
        )

    unit_price = money(product.price)
    original_total_price = money(unit_price * requested_quantity)
    applied_voucher = None
    discount_amount = money(0)
    total_price = original_total_price
    clean_voucher_code = (voucher_code or "").strip()
    if clean_voucher_code:
        voucher_validation = await voucher_service.validate_voucher(
            session=session,
            code=clean_voucher_code,
            user_id=user_id,
            product=product,
            quantity=requested_quantity,
            order_amount=original_total_price,
        )
        if not voucher_validation.ok or not voucher_validation.voucher:
            return WalletResult(False, voucher_validation.message)
        applied_voucher = voucher_validation.voucher
        discount_amount = money(voucher_validation.discount_amount)
        total_price = money(voucher_validation.final_amount)

    balance = money(user.wallet_balance)
    if balance < total_price:
        return WalletResult(False, f"Số dư ví không đủ. Cần thêm {format_vnd(total_price - balance)}.")

    now = datetime.utcnow()
    user.wallet_balance = balance - total_price
    user.total_spent = money(user.total_spent) + total_price
    debit = WalletTransaction(
        user_id=user_id,
        tx_type=WalletTxType.PURCHASE,
        amount=total_price,
        status=WalletTxStatus.SUCCESS,
        reference=f"BUY{user_id}-{product_id}-{int(now.timestamp())}",
        provider="wallet",
        note=(
            f"Mua {requested_quantity} x sản phẩm #{product_id}"
            + (f" | voucher {voucher_service.normalize_code(clean_voucher_code)} giảm {format_vnd(discount_amount)}" if discount_amount > 0 else "")
        ),
        completed_at=now,
    )
    session.add(debit)
    order = await order_service.create_order(
        session=session,
        user_id=user_id,
        product_id=product_id,
        quantity=requested_quantity,
        total_amount=float(total_price),
        payment_method="wallet",
        commit=False,
        original_amount=float(original_total_price),
        discount_amount=float(discount_amount),
        voucher_code=voucher_service.normalize_code(clean_voucher_code) if applied_voucher else None,
    )
    paid_result = await order_payment_service.mark_order_paid(
        session=session,
        order=order,
        payment_method=payment_policy_service.PAYMENT_METHOD_WALLET,
        payment_note="Thanh toán thành công bằng ví",
        paid_at=now,
    )
    if not paid_result.success:
        await session.rollback()
        return WalletResult(False, paid_result.message, debit, order)
    if applied_voucher:
        await voucher_service.mark_voucher_used(session, applied_voucher.id)
    await session.flush()

    discount_lines = ""
    if applied_voucher and discount_amount > 0:
        discount_lines = (
            f"Mã giảm giá: <b>{escape(order.voucher_code or applied_voucher.code)}</b>\n"
            f"Giảm giá: <b>{format_vnd(discount_amount)}</b>\n"
            f"Giá gốc: <b>{format_vnd(original_total_price)}</b>\n"
        )

    summary_text = (
        f"🎉 <b>Mua hàng thành công!</b>\n\n"
        f"Mã đơn hàng: <b>{escape(get_order_code(order))}</b>\n"
        f"Sản phẩm: <b>{escape(product.name)}</b>\n"
        f"Số lượng: <b>{requested_quantity}</b>\n"
        f"{discount_lines}"
        f"Số tiền thanh toán: <b>{format_vnd(total_price)}</b>\n"
        f"Số dư còn lại: <b>{format_vnd(user.wallet_balance)}</b>\n\n"
        "Bot sẽ gửi thông tin sản phẩm cho bạn trong một tin nhắn riêng ngay sau đây."
    )
    try:
        await bot.send_message(chat_id=user_id, text=summary_text)
        complete_result = await order_payment_service.complete_paid_order(session, bot, order)
        if not complete_result.success:
            await session.rollback()
            return WalletResult(False, complete_result.message, debit, order)
    except Exception:
        logger.exception("Failed to deliver wallet purchase", extra={"user_id": user_id, "product_id": product_id, "order_id": order.id if order else None})
        await session.rollback()
        return WalletResult(False, "Telegram gửi hàng thất bại. Ví chưa bị trừ tiền.", debit, order)

    await session.refresh(order)
    return WalletResult(True, "Đã trừ ví và giao hàng thành công.", debit, order)
