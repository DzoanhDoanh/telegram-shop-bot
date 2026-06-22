import time
from urllib.parse import quote

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.database.models import Category, InventoryItem, Product
from app.database.session import async_session
from app.services.notification_service import (
    ANNOUNCEMENT_TYPE_NEW,
    ANNOUNCEMENT_TYPE_REMINDER,
    announce_new_product,
    announce_product,
)
from app.web.audit import write_audit_event
from app.web.auth import validate_csrf_token

router = APIRouter()


def bind_routes(
    templates,
    template_context,
    is_authenticated,
    redirect_login,
    bot_getter,
):
    @router.get("/admin/products", response_class=HTMLResponse)
    async def products_page(request: Request, msg: str = "", q: str = "", category_id: str = "", page: int = 1):
        if not is_authenticated(request):
            return redirect_login()

        try:
            selected_category_id = int(category_id) if category_id else None
        except ValueError:
            selected_category_id = None

        page = max(page, 1)
        per_page = 24

        async with async_session() as session:
            categories_result = await session.execute(
                select(Category).where(Category.is_active == True).order_by(Category.name.asc())
            )
            categories = categories_result.scalars().all()

            stock_subquery = (
                select(
                    InventoryItem.product_id.label("product_id"),
                    func.count(InventoryItem.id).label("stock"),
                )
                .where(InventoryItem.is_sold == False)
                .group_by(InventoryItem.product_id)
                .subquery()
            )

            product_query = (
                select(Product, func.coalesce(stock_subquery.c.stock, 0).label("stock"))
                .options(selectinload(Product.category))
                .outerjoin(stock_subquery, stock_subquery.c.product_id == Product.id)
                .where(Product.is_active == True)
            )
            if q:
                product_query = product_query.where(
                    (Product.name.ilike(f"%{q}%")) | (Product.description.ilike(f"%{q}%"))
                )
            if selected_category_id:
                product_query = product_query.where(Product.category_id == selected_category_id)

            count_query = select(func.count()).select_from(product_query.order_by(None).subquery())
            total_count = await session.scalar(count_query) or 0
            total_pages = max((total_count + per_page - 1) // per_page, 1)
            if page > total_pages:
                page = total_pages

            result = await session.execute(
                product_query.order_by(Product.created_at.desc(), Product.id.desc())
                .offset((page - 1) * per_page)
                .limit(per_page)
            )
            rows = result.all()

            products = []
            for p, stock in rows:
                products.append({
                    "id": p.id,
                    "category_id": p.category_id,
                    "name": p.name,
                    "price": p.price,
                    "description": p.description,
                    "category": p.category,
                    "stock": int(stock or 0),
                    "delivery_mode": p.delivery_mode,
                    "payment_mode": p.payment_mode,
                    "fixed_delivery_content": p.fixed_delivery_content,
                    "is_bundle": bool(p.is_bundle),
                    "bundle_items_text": p.bundle_items_text,
                    "allow_quantity_selection": p.allow_quantity_selection,
                    "min_quantity": p.min_quantity,
                    "max_quantity": p.max_quantity,
                })

        return templates.TemplateResponse(
            request,
            "products.html",
            template_context(
                request,
                active_page="products",
                products=products,
                categories=categories,
                q=q,
                category_id=selected_category_id,
                current_page=page,
                total_pages=total_pages,
                total_count=total_count,
                per_page=per_page,
                msg=msg,
            ),
        )

    @router.post("/admin/products/add")
    async def add_product_web(
        request: Request,
        name: str = Form(...),
        price: float = Form(...),
        description: str = Form(""),
        category_id: int | None = Form(None),
        new_category: str = Form(""),
        delivery_mode: str = Form("inventory"),
        payment_mode: str = Form("wallet_only"),
        fixed_delivery_content: str = Form(""),
        is_bundle: bool = Form(False),
        bundle_items_text: str = Form(""),
        allow_quantity_selection: bool = Form(False),
        min_quantity: int = Form(1),
        max_quantity: int = Form(1),
        csrf_token: str = Form(...),
    ):
        if not is_authenticated(request):
            return redirect_login()
        if not validate_csrf_token(request, csrf_token):
            return RedirectResponse('/login', status_code=302)

        normalized_delivery_mode = delivery_mode if delivery_mode in {"inventory", "fixed_content"} else "inventory"
        normalized_payment_mode = payment_mode if payment_mode in {"wallet_only", "direct_bank_only", "wallet_or_direct_bank"} else "wallet_only"
        normalized_fixed_delivery_content = fixed_delivery_content.strip() or None
        quantity_enabled = bool(allow_quantity_selection)
        min_quantity = max(1, int(min_quantity or 1))
        max_quantity = max(min_quantity, int(max_quantity or 1))
        if normalized_delivery_mode == "fixed_content":
            quantity_enabled = False
            min_quantity = 1
            max_quantity = 1
        elif not quantity_enabled:
            min_quantity = 1
            max_quantity = 1

        async with async_session() as session:
            cat = None
            if category_id:
                cat = await session.scalar(
                    select(Category).where(Category.id == category_id, Category.is_active == True)
                )
            if not cat and new_category.strip():
                cat = Category(name=new_category.strip(), emoji="📦")
                session.add(cat)
                await session.flush()
            if not cat:
                cat = await session.scalar(select(Category).where(Category.is_active == True).limit(1))
            if not cat:
                cat = Category(name="General", emoji="📦")
                session.add(cat)
                await session.flush()

            product = Product(
                category_id=cat.id,
                name=name.strip(),
                price=price,
                description=description.strip() or None,
                delivery_mode=normalized_delivery_mode,
                payment_mode=normalized_payment_mode,
                fixed_delivery_content=normalized_fixed_delivery_content,
                is_bundle=bool(is_bundle),
                bundle_items_text=bundle_items_text.strip() or None,
                allow_quantity_selection=quantity_enabled,
                min_quantity=min_quantity,
                max_quantity=max_quantity,
            )
            session.add(product)
            await session.commit()
            await session.refresh(product)
            product_id_value = product.id

        write_audit_event(request, "product_add", product_id=product_id_value, name=name, announcement_sent=0)
        msg = f"Đã thêm sản phẩm '{name}' thành công. Thông báo sẽ chỉ được gửi khi sản phẩm có hàng trong kho."
        return RedirectResponse(f"/admin/products?msg={quote(msg)}", status_code=302)

    @router.post("/admin/products/{product_id}/edit")
    async def edit_product_web(
        product_id: int,
        request: Request,
        name: str = Form(...),
        price: float = Form(...),
        description: str = Form(""),
        category_id: int | None = Form(None),
        new_category: str = Form(""),
        delivery_mode: str = Form("inventory"),
        payment_mode: str = Form("wallet_only"),
        fixed_delivery_content: str = Form(""),
        is_bundle: bool = Form(False),
        bundle_items_text: str = Form(""),
        allow_quantity_selection: bool = Form(False),
        min_quantity: int = Form(1),
        max_quantity: int = Form(1),
        csrf_token: str = Form(...),
    ):
        if not is_authenticated(request):
            return redirect_login()
        if not validate_csrf_token(request, csrf_token):
            return RedirectResponse('/login', status_code=302)

        normalized_delivery_mode = delivery_mode if delivery_mode in {"inventory", "fixed_content"} else "inventory"
        normalized_payment_mode = payment_mode if payment_mode in {"wallet_only", "direct_bank_only", "wallet_or_direct_bank"} else "wallet_only"
        normalized_fixed_delivery_content = fixed_delivery_content.strip() or None
        quantity_enabled = bool(allow_quantity_selection)
        min_quantity = max(1, int(min_quantity or 1))
        max_quantity = max(min_quantity, int(max_quantity or 1))
        if normalized_delivery_mode == "fixed_content":
            quantity_enabled = False
            min_quantity = 1
            max_quantity = 1
        elif not quantity_enabled:
            min_quantity = 1
            max_quantity = 1

        async with async_session() as session:
            product = await session.get(Product, product_id)
            if not product or not product.is_active:
                return RedirectResponse("/admin/products?msg=Sản phẩm không tồn tại", status_code=302)

            cat = None
            if category_id:
                cat = await session.scalar(
                    select(Category).where(Category.id == category_id, Category.is_active == True)
                )
            if not cat and new_category.strip():
                cat = Category(name=new_category.strip(), emoji="📦")
                session.add(cat)
                await session.flush()
            if not cat:
                cat = await session.scalar(
                    select(Category).where(Category.id == product.category_id, Category.is_active == True)
                )
            if not cat:
                cat = await session.scalar(select(Category).where(Category.is_active == True).limit(1))
            if not cat:
                cat = Category(name="General", emoji="📦")
                session.add(cat)
                await session.flush()

            product.name = name.strip()
            product.price = price
            product.description = description.strip() or None
            product.category_id = cat.id
            product.delivery_mode = normalized_delivery_mode
            product.payment_mode = normalized_payment_mode
            product.fixed_delivery_content = normalized_fixed_delivery_content
            product.is_bundle = bool(is_bundle)
            product.bundle_items_text = bundle_items_text.strip() or None
            product.allow_quantity_selection = quantity_enabled
            product.min_quantity = min_quantity
            product.max_quantity = max_quantity
            await session.commit()

        write_audit_event(request, "product_edit", product_id=product_id, name=name)
        return RedirectResponse(f"/admin/products?msg=Đã cập nhật sản phẩm '{name}'", status_code=302)

    @router.post("/admin/products/{product_id}/disable")
    async def disable_product_web(product_id: int, request: Request, csrf_token: str = Form(...)):
        if not is_authenticated(request):
            return redirect_login()
        if not validate_csrf_token(request, csrf_token):
            return RedirectResponse('/login', status_code=302)

        async with async_session() as session:
            product = await session.get(Product, product_id)
            if not product or not product.is_active:
                return RedirectResponse("/admin/products?msg=Sản phẩm không tồn tại", status_code=302)
            product_name = product.name
            product.is_active = False
            await session.commit()

        write_audit_event(request, "product_disable", product_id=product_id, name=product_name)
        return RedirectResponse(f"/admin/products?msg=Đã xóa sản phẩm #{product_id} khỏi shop", status_code=302)

    @router.post("/admin/products/{product_id}/announce")
    async def announce_product_web(
        product_id: int,
        request: Request,
        kind: str = Form(...),
        csrf_token: str = Form(...),
    ):
        if not is_authenticated(request):
            return redirect_login()
        if not validate_csrf_token(request, csrf_token):
            return RedirectResponse('/login', status_code=302)

        if kind not in {ANNOUNCEMENT_TYPE_NEW, ANNOUNCEMENT_TYPE_REMINDER}:
            return RedirectResponse(f"/admin/products?msg={quote('Loại thông báo không hợp lệ')}", status_code=302)

        bot = bot_getter()
        async with async_session() as session:
            product = await session.get(Product, product_id, options=[selectinload(Product.category)])
            if not product or not product.is_active:
                return RedirectResponse(f"/admin/products?msg={quote('Sản phẩm không tồn tại hoặc đã ngừng bán')}", status_code=302)

            stock = await session.scalar(
                select(func.count(InventoryItem.id)).where(
                    InventoryItem.product_id == product_id,
                    InventoryItem.is_sold == False,
                )
            ) or 0
            if product.delivery_mode != "fixed_content" and stock <= 0:
                msg = f"Không thể gửi thông báo cho sản phẩm '{product.name}' vì hiện đang hết hàng."
                return RedirectResponse(f"/admin/products?msg={quote(msg)}", status_code=302)

            sent = 0
            try:
                sent = await announce_product(bot, session, product_id, kind)
            except Exception:
                sent = 0

        kind_label = "sản phẩm mới" if kind == ANNOUNCEMENT_TYPE_NEW else "nhắc lại sản phẩm cũ"
        write_audit_event(request, "product_announce", product_id=product_id, kind=kind, sent=sent)
        msg = f"Đã gửi thông báo {kind_label} cho sản phẩm #{product_id} tới {sent} người dùng."
        return RedirectResponse(f"/admin/products?msg={quote(msg)}", status_code=302)

    return router
