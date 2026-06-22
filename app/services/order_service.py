from datetime import datetime

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.models import Order, OrderStatus
from app.services import payment_policy_service
from app.services.order_code import format_order_code


async def create_order(
    session: AsyncSession,
    user_id: int,
    product_id: int,
    quantity: int,
    total_amount: float,
    payment_method: str = "bank_transfer",
    commit: bool = True,
    original_amount: float | None = None,
    discount_amount: float | None = None,
    voucher_code: str | None = None,
) -> Order:
    next_id = await session.scalar(text("SELECT nextval('orders_id_seq')"))
    if next_id is None:
        raise RuntimeError("Không thể tạo mã đơn hàng mới.")

    order_code = format_order_code(int(next_id))
    order = Order(
        id=int(next_id),
        order_code=order_code,
        user_id=user_id,
        product_id=product_id,
        quantity=quantity,
        original_amount=original_amount,
        discount_amount=discount_amount,
        total_amount=total_amount,
        voucher_code=voucher_code,
        status=OrderStatus.PENDING_PAYMENT,
        payment_method=payment_method,
        bank_transfer_reference_normalized=(
            payment_policy_service.build_direct_bank_reference(order_code)
            if payment_method == payment_policy_service.PAYMENT_METHOD_DIRECT_BANK
            else None
        ),
    )
    session.add(order)
    await session.flush()
    if commit:
        await session.commit()
        await session.refresh(order)
    return order


async def update_payment_proof(session: AsyncSession, order_id: int, proof_file_id: str):
    order = await session.get(Order, order_id)
    if order:
        order.payment_proof = proof_file_id
        await session.commit()


async def get_pending_order(session: AsyncSession, order_id: int) -> Order | None:
    order = await session.get(Order, order_id)
    if order and order.status == OrderStatus.PENDING_PAYMENT:
        return order
    return None


async def reject_order(session: AsyncSession, order_id: int, reason: str = "") -> Order | None:
    result = await session.execute(
        select(Order)
        .where(Order.id == order_id)
        .with_for_update()
    )
    order = result.scalar_one_or_none()
    if order and order.status == OrderStatus.PENDING_PAYMENT:
        order.status = OrderStatus.CANCELLED
        clean_reason = reason.strip()
        if clean_reason:
            order.payment_note = clean_reason
        order.completed_at = datetime.utcnow()
        await session.commit()
        await session.refresh(order)
        return order
    return None
