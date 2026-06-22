from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Product, Voucher, VoucherDiscountType


@dataclass(slots=True)
class VoucherValidation:
    ok: bool
    message: str
    voucher: Voucher | None = None
    discount_amount: Decimal = Decimal("0")
    final_amount: Decimal = Decimal("0")


def money(value: object) -> Decimal:
    if value is None:
        return Decimal("0")
    return Decimal(str(value)).quantize(Decimal("1"))


def normalize_code(code: str) -> str:
    return "".join((code or "").strip().upper().split())


def format_discount(voucher: Voucher) -> str:
    if voucher.discount_type == VoucherDiscountType.PERCENT:
        return f"{money(voucher.discount_value)}%"
    return f"{money(voucher.discount_value):,.0f}đ"


def calculate_discount(voucher: Voucher, order_amount: object) -> Decimal:
    amount = money(order_amount)
    if amount <= 0:
        return Decimal("0")
    if voucher.discount_type == VoucherDiscountType.PERCENT:
        percent = max(Decimal("0"), money(voucher.discount_value))
        discount = (amount * percent / Decimal("100")).quantize(Decimal("1"))
    else:
        discount = money(voucher.discount_value)
    if voucher.max_discount_amount is not None and money(voucher.max_discount_amount) > 0:
        discount = min(discount, money(voucher.max_discount_amount))
    return max(Decimal("0"), min(discount, amount))


async def list_vouchers(session: AsyncSession) -> list[Voucher]:
    result = await session.execute(select(Voucher).order_by(Voucher.created_at.desc(), Voucher.id.desc()))
    return list(result.scalars().all())


async def get_active_voucher_by_code(session: AsyncSession, code: str) -> Voucher | None:
    normalized = normalize_code(code)
    if not normalized:
        return None
    return await session.scalar(select(Voucher).where(func.upper(Voucher.code) == normalized).limit(1))


async def validate_voucher(
    session: AsyncSession,
    code: str,
    user_id: int,
    product: Product,
    quantity: int,
    order_amount: object,
) -> VoucherValidation:
    voucher = await get_active_voucher_by_code(session, code)
    total = money(order_amount)
    if not voucher:
        return VoucherValidation(False, "Mã giảm giá không tồn tại.", final_amount=total)
    if not voucher.is_active:
        return VoucherValidation(False, "Mã giảm giá đang tạm tắt.", voucher=voucher, final_amount=total)

    now = datetime.utcnow()
    if voucher.starts_at and voucher.starts_at > now:
        return VoucherValidation(False, "Mã giảm giá chưa đến thời gian sử dụng.", voucher=voucher, final_amount=total)
    if voucher.expires_at and voucher.expires_at < now:
        return VoucherValidation(False, "Mã giảm giá đã hết hạn.", voucher=voucher, final_amount=total)
    if voucher.usage_limit is not None and voucher.used_count >= voucher.usage_limit:
        return VoucherValidation(False, "Mã giảm giá đã hết lượt sử dụng.", voucher=voucher, final_amount=total)
    if money(voucher.min_order_amount) > 0 and total < money(voucher.min_order_amount):
        return VoucherValidation(False, "Đơn hàng chưa đạt giá trị tối thiểu để dùng mã này.", voucher=voucher, final_amount=total)
    if voucher.applies_product_id and voucher.applies_product_id != product.id:
        return VoucherValidation(False, "Mã giảm giá không áp dụng cho sản phẩm này.", voucher=voucher, final_amount=total)
    if voucher.applies_category_id and voucher.applies_category_id != product.category_id:
        return VoucherValidation(False, "Mã giảm giá không áp dụng cho danh mục này.", voucher=voucher, final_amount=total)

    discount = calculate_discount(voucher, total)
    if discount <= 0:
        return VoucherValidation(False, "Mã giảm giá không tạo ra số tiền giảm hợp lệ.", voucher=voucher, final_amount=total)
    return VoucherValidation(True, "Mã giảm giá hợp lệ.", voucher=voucher, discount_amount=discount, final_amount=max(Decimal("0"), total - discount))


async def mark_voucher_used(session: AsyncSession, voucher_id: int) -> None:
    voucher = await session.get(Voucher, voucher_id, with_for_update=True)
    if voucher:
        voucher.used_count = int(voucher.used_count or 0) + 1
