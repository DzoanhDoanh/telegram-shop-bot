from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.models import Category, Product, InventoryItem

async def get_categories(session: AsyncSession) -> list[Category]:
    result = await session.execute(select(Category).where(Category.is_active == True))
    return list(result.scalars().all())

async def get_products_by_category(session: AsyncSession, category_id: int) -> list[Product]:
    result = await session.execute(
        select(Product)
        .where(Product.category_id == category_id, Product.is_active == True)
    )
    return list(result.scalars().all())

async def get_product(session: AsyncSession, product_id: int) -> Product | None:
    return await session.get(Product, product_id)


async def search_products(session: AsyncSession, query: str, limit: int = 10) -> list[Product]:
    keyword = f"%{query.strip()}%"
    result = await session.execute(
        select(Product)
        .where(
            Product.is_active == True,
            or_(
                Product.name.ilike(keyword),
                Product.description.ilike(keyword),
            ),
        )
        .order_by(Product.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_stock_count(session: AsyncSession, product_id: int) -> int:
    result = await session.execute(
        select(func.count(InventoryItem.id))
        .where(InventoryItem.product_id == product_id, InventoryItem.is_sold == False)
    )
    return result.scalar() or 0


async def get_stock_counts(session: AsyncSession, product_ids: list[int]) -> dict[int, int]:
    if not product_ids:
        return {}

    result = await session.execute(
        select(
            InventoryItem.product_id,
            func.count(InventoryItem.id),
        )
        .where(
            InventoryItem.product_id.in_(product_ids),
            InventoryItem.is_sold == False,
        )
        .group_by(InventoryItem.product_id)
    )
    counts = {product_id: count for product_id, count in result.all()}
    return {product_id: int(counts.get(product_id, 0)) for product_id in product_ids}
