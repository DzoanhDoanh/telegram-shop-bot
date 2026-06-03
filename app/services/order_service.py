from sqlalchemy.ext.asyncio import AsyncSession
from app.database.models import Order, OrderStatus


async def create_order(
    session: AsyncSession,
    user_id: int,
    product_id: int,
    quantity: int,
    total_amount: float,
    payment_method: str = "bank_transfer",
    commit: bool = True,
) -> Order:
    order = Order(
        user_id=user_id,
        product_id=product_id,
        quantity=quantity,
        total_amount=total_amount,
        status=OrderStatus.PENDING_PAYMENT,
        payment_method=payment_method,
    )
    session.add(order)
    if commit:
        await session.commit()
        await session.refresh(order)
    else:
        await session.flush()
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


async def reject_order(session: AsyncSession, order_id: int) -> Order | None:
    order = await session.get(Order, order_id)
    if order and order.status == OrderStatus.PENDING_PAYMENT:
        order.status = OrderStatus.CANCELLED
        await session.commit()
        return order
    return None
