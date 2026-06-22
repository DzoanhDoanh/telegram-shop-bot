from fastapi import APIRouter, Request

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.database.models import InventoryItem, Order, Product
from app.database.session import async_session
from app.web.audit import write_audit_event

router = APIRouter()


def bind_routes(is_authenticated, redirect_login, csv_response):
    @router.get("/admin/export/orders.csv")
    async def export_orders_csv(request: Request):
        if not is_authenticated(request):
            return redirect_login()

        async with async_session() as session:
            result = await session.execute(
                select(Order)
                .options(selectinload(Order.product), selectinload(Order.user))
                .order_by(Order.created_at.desc())
            )
            orders = result.scalars().all()

            rows = []
            for order in orders:
                rows.append({
                    'id': order.id,
                    'user_id': order.user_id,
                    'product_name': order.product.name if order.product else '',
                    'status': order.status.value,
                    'quantity': order.quantity,
                    'total_amount': float(order.total_amount),
                    'created_at': order.created_at.isoformat() if order.created_at else '',
                    'completed_at': order.completed_at.isoformat() if order.completed_at else '',
                })

        write_audit_event(request, "export_orders_csv", count=len(rows))
        return csv_response('orders.csv', rows)

    @router.get("/admin/export/products.csv")
    async def export_products_csv(request: Request):
        if not is_authenticated(request):
            return redirect_login()

        async with async_session() as session:
            result = await session.execute(
                select(Product)
                .options(selectinload(Product.category))
                .where(Product.is_active == True)
                .order_by(Product.created_at.desc())
            )
            products = result.scalars().all()

            rows = []
            for product in products:
                stock = await session.scalar(
                    select(func.count(InventoryItem.id)).where(
                        InventoryItem.product_id == product.id,
                        InventoryItem.is_sold == False
                    )
                ) or 0

                rows.append({
                    'id': product.id,
                    'category_name': product.category.name if product.category else '',
                    'name': product.name,
                    'price': float(product.price),
                    'stock': stock,
                    'is_active': product.is_active,
                    'created_at': product.created_at.isoformat() if product.created_at else '',
                })

        write_audit_event(request, "export_products_csv", count=len(rows))
        return csv_response('products.csv', rows)

    @router.get("/admin/export/inventory.csv")
    async def export_inventory_csv(request: Request):
        if not is_authenticated(request):
            return redirect_login()

        async with async_session() as session:
            result = await session.execute(
                select(Product).where(Product.is_active == True).order_by(Product.name.asc())
            )
            products = result.scalars().all()

            rows = []
            for product in products:
                available = await session.scalar(
                    select(func.count(InventoryItem.id)).where(
                        InventoryItem.product_id == product.id,
                        InventoryItem.is_sold == False
                    )
                ) or 0

                sold = await session.scalar(
                    select(func.count(InventoryItem.id)).where(
                        InventoryItem.product_id == product.id,
                        InventoryItem.is_sold == True
                    )
                ) or 0

                rows.append({
                    'product_id': product.id,
                    'product_name': product.name,
                    'available': available,
                    'sold': sold,
                    'total': available + sold,
                })

        write_audit_event(request, "export_inventory_csv", count=len(rows))
        return csv_response('inventory.csv', rows)

    return router
