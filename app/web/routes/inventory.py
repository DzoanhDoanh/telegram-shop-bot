from urllib.parse import quote

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select

from app.database.models import InventoryItem, Product
from app.database.session import async_session
from app.web.audit import write_audit_event
from app.web.auth import validate_csrf_token

router = APIRouter()


def _normalize_lines(raw_text: str) -> tuple[list[str], int, int]:
    lines = raw_text.splitlines()
    seen: set[str] = set()
    unique_items: list[str] = []
    blank_count = 0
    duplicate_count = 0

    for line in lines:
        item = line.strip()
        if not item:
            blank_count += 1
            continue
        if item in seen:
            duplicate_count += 1
            continue
        seen.add(item)
        unique_items.append(item)

    return unique_items, blank_count, duplicate_count


def bind_routes(templates, template_context, is_authenticated, redirect_login, redirect_back):
    @router.get("/admin/inventory", response_class=HTMLResponse)
    async def inventory_page(request: Request, msg: str = "", product_id: str = "", page: int = 1):
        if not is_authenticated(request):
            return redirect_login()

        try:
            selected_product_id = int(product_id) if product_id else None
        except ValueError:
            selected_product_id = None

        page = max(page, 1)
        per_page = 20

        async with async_session() as session:
            stock_subquery = (
                select(
                    InventoryItem.product_id.label("product_id"),
                    func.count(InventoryItem.id).label("stock"),
                )
                .where(InventoryItem.is_sold == False)
                .group_by(InventoryItem.product_id)
                .subquery()
            )

            active_products_result = await session.execute(
                select(Product, func.coalesce(stock_subquery.c.stock, 0).label("stock"))
                .outerjoin(stock_subquery, stock_subquery.c.product_id == Product.id)
                .where(Product.is_active == True)
                .order_by(Product.name.asc())
            )
            all_products_rows = active_products_result.all()

            products_for_stock = []
            fixed_content_products = []
            for product, stock in all_products_rows:
                payload = {
                    "id": product.id,
                    "name": product.name,
                    "price": product.price,
                    "stock": int(stock or 0),
                    "delivery_mode": product.delivery_mode,
                }
                if product.delivery_mode == "fixed_content":
                    fixed_content_products.append(payload)
                else:
                    products_for_stock.append(payload)

            total_count = len(products_for_stock)
            total_pages = max((total_count + per_page - 1) // per_page, 1)
            if page > total_pages:
                page = total_pages

            start_index = (page - 1) * per_page
            end_index = start_index + per_page
            paged_products = products_for_stock[start_index:end_index]

        return templates.TemplateResponse(
            request,
            "inventory.html",
            template_context(
                request,
                active_page="inventory",
                msg=msg,
                products=paged_products,
                total_count=total_count,
                current_page=page,
                total_pages=total_pages,
                selected_product_id=selected_product_id,
                fixed_content_products=fixed_content_products,
            ),
        )

    @router.post("/admin/inventory/add")
    async def add_inventory_items(
        request: Request,
        product_id: int = Form(...),
        keys: str = Form(""),
        dry_run: int = Form(1),
        csrf_token: str = Form(...),
    ):
        if not is_authenticated(request):
            return redirect_login()
        if not validate_csrf_token(request, csrf_token):
            return RedirectResponse("/login", status_code=302)

        normalized_items, blank_count, duplicate_count = _normalize_lines(keys)
        if not normalized_items:
            return redirect_back("/admin/inventory", "Không có dòng hợp lệ để nạp kho")

        async with async_session() as session:
            product = await session.get(Product, product_id)
            if not product or not product.is_active:
                return redirect_back("/admin/inventory", "Sản phẩm không tồn tại hoặc đã ngừng bán")
            if product.delivery_mode == "fixed_content":
                return redirect_back("/admin/inventory", "Sản phẩm này dùng nội dung có sẵn nên không cần nạp kho")

            if dry_run == 1:
                msg = (
                    f"Preview: sẽ nạp {len(normalized_items)} dòng cho '{product.name}'. "
                    f"Bỏ qua {blank_count} dòng trống và {duplicate_count} dòng trùng trong ô nhập."
                )
                return RedirectResponse(
                    f"/admin/inventory?product_id={product_id}&msg={quote(msg)}",
                    status_code=302,
                )

            for item in normalized_items:
                session.add(InventoryItem(product_id=product_id, content=item, is_sold=False))
            await session.commit()

        write_audit_event(
            request,
            "inventory_add",
            product_id=product_id,
            added_count=len(normalized_items),
            blank_count=blank_count,
            duplicate_count=duplicate_count,
        )
        msg = (
            f"Đã nạp {len(normalized_items)} dòng vào kho cho sản phẩm #{product_id}. "
            f"Bỏ qua {blank_count} dòng trống và {duplicate_count} dòng trùng trong ô nhập."
        )
        return RedirectResponse(f"/admin/inventory?product_id={product_id}&msg={quote(msg)}", status_code=302)

    return router
