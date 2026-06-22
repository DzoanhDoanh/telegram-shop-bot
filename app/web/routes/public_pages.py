from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, or_, select

from app.database.models import Category, InventoryItem, Product
from app.database.session import async_session
from app.services.app_config_service import get_app_config_view

router = APIRouter()


def _support_url(app_config) -> str | None:
    username = (getattr(app_config, "support_username", "") or "").strip().lstrip("@")
    if not username:
        return None
    return f"https://t.me/{username}"


def _public_layout_context(app_config, **kwargs):
    return {
        "app_config": app_config,
        "support_url": _support_url(app_config),
        "nav_links": [
            {"label": "Trang chủ", "href": "/"},
            {"label": "Sản phẩm", "href": "/store"},
            {"label": "Điều khoản", "href": "/terms"},
            {"label": "Hỗ trợ", "href": "/support-policy"},
        ],
        **kwargs,
    }


def _product_card_payload(product, stock: int, category):
    is_fixed = product.delivery_mode == "fixed_content"
    is_available = True if is_fixed else int(stock or 0) > 0
    return {
        "id": product.id,
        "name": product.name,
        "description": product.description,
        "price": product.price,
        "image_url": product.image_url,
        "category": category,
        "stock": int(stock or 0),
        "delivery_mode": product.delivery_mode,
        "is_bundle": bool(getattr(product, "is_bundle", False)),
        "bundle_items_text": getattr(product, "bundle_items_text", None),
        "allow_quantity_selection": bool(product.allow_quantity_selection and not is_fixed),
        "min_quantity": product.min_quantity or 1,
        "max_quantity": product.max_quantity or 1,
        "is_available": is_available,
        "is_fixed_content": is_fixed,
        "has_quantity_range": bool(product.allow_quantity_selection and not is_fixed),
        "highlight_badges": [
            badge for badge in [
                "Combo tiết kiệm" if bool(getattr(product, "is_bundle", False)) else None,
                "Giao tự động" if is_fixed else None,
                "Cho chọn số lượng" if bool(product.allow_quantity_selection and not is_fixed) else None,
                "Còn hàng" if (not is_fixed and int(stock or 0) > 0) else None,
            ] if badge
        ],
    }


def _apply_store_sort(query, sort: str, stock_subquery):
    stock_expr = func.coalesce(stock_subquery.c.stock, 0)
    if sort == "price_asc":
        return query.order_by(Product.price.asc(), Product.created_at.desc(), Product.id.desc())
    if sort == "price_desc":
        return query.order_by(Product.price.desc(), Product.created_at.desc(), Product.id.desc())
    if sort == "name_asc":
        return query.order_by(Product.name.asc(), Product.created_at.desc(), Product.id.desc())
    if sort == "best_value":
        return query.order_by(Product.allow_quantity_selection.desc(), stock_expr.desc(), Product.price.asc(), Product.created_at.desc(), Product.id.desc())
    return query.order_by(Product.created_at.desc(), Product.id.desc())


def bind_routes(templates):
    @router.get("/", response_class=HTMLResponse)
    async def public_home_page(request: Request):
        async with async_session() as session:
            app_config = await get_app_config_view(session)
            categories = list((await session.execute(
                select(Category).where(Category.is_active == True).order_by(Category.name.asc()).limit(8)
            )).scalars().all())

            stock_subquery = (
                select(
                    InventoryItem.product_id.label("product_id"),
                    func.count(InventoryItem.id).label("stock"),
                )
                .where(InventoryItem.is_sold == False)
                .group_by(InventoryItem.product_id)
                .subquery()
            )
            rows = (await session.execute(
                select(Product, func.coalesce(stock_subquery.c.stock, 0).label("stock"), Category)
                .join(Category, Category.id == Product.category_id)
                .outerjoin(stock_subquery, stock_subquery.c.product_id == Product.id)
                .where(Product.is_active == True, Category.is_active == True)
                .order_by(Product.created_at.desc(), Product.id.desc())
                .limit(6)
            )).all()

            featured_products = []
            for product, stock, category in rows:
                featured_products.append(_product_card_payload(product, int(stock or 0), category))

        return templates.TemplateResponse(
            request,
            "public_home.html",
            _public_layout_context(
                app_config,
                page_title=app_config.shop_display_name,
                categories=categories,
                featured_products=featured_products,
            ),
        )

    @router.get("/terms", response_class=HTMLResponse)
    async def public_terms_page(request: Request):
        async with async_session() as session:
            app_config = await get_app_config_view(session)
        return templates.TemplateResponse(
            request,
            "public_terms.html",
            _public_layout_context(
                app_config,
                page_title="Điều khoản mua hàng",
                content_html=app_config.terms_text,
            ),
        )

    @router.get("/support-policy", response_class=HTMLResponse)
    async def public_support_policy_page(request: Request):
        async with async_session() as session:
            app_config = await get_app_config_view(session)
        return templates.TemplateResponse(
            request,
            "public_terms.html",
            _public_layout_context(
                app_config,
                page_title="Hỗ trợ & hậu mãi",
                content_html=app_config.support_text,
            ),
        )

    @router.get("/store", response_class=HTMLResponse)
    async def public_store_page(request: Request, q: str = "", category_id: str = "", availability: str = "", sort: str = "newest", page: int = 1):
        page = max(page, 1)
        per_page = 12
        try:
            selected_category_id = int(category_id) if category_id else None
        except ValueError:
            selected_category_id = None

        async with async_session() as session:
            app_config = await get_app_config_view(session)
            categories = list((await session.execute(
                select(Category).where(Category.is_active == True).order_by(Category.name.asc())
            )).scalars().all())

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
                select(Product, func.coalesce(stock_subquery.c.stock, 0).label("stock"), Category)
                .join(Category, Category.id == Product.category_id)
                .outerjoin(stock_subquery, stock_subquery.c.product_id == Product.id)
                .where(Product.is_active == True, Category.is_active == True)
            )
            if q.strip():
                keyword = f"%{q.strip()}%"
                product_query = product_query.where(
                    or_(Product.name.ilike(keyword), Product.description.ilike(keyword))
                )
            if selected_category_id:
                product_query = product_query.where(Product.category_id == selected_category_id)
            if availability == "in_stock":
                product_query = product_query.where(
                    or_(Product.delivery_mode == "fixed_content", func.coalesce(stock_subquery.c.stock, 0) > 0)
                )

            count_query = select(func.count()).select_from(product_query.order_by(None).subquery())
            total_count = await session.scalar(count_query) or 0
            total_pages = max((total_count + per_page - 1) // per_page, 1)
            if page > total_pages:
                page = total_pages

            rows = (await session.execute(
                _apply_store_sort(product_query, sort, stock_subquery)
                .offset((page - 1) * per_page)
                .limit(per_page)
            )).all()

            products = []
            for product, stock, category in rows:
                products.append(_product_card_payload(product, int(stock or 0), category))

        return templates.TemplateResponse(
            request,
            "public_store.html",
            _public_layout_context(
                app_config,
                page_title="Sản phẩm đang bán",
                products=products,
                categories=categories,
                current_query=q,
                selected_category_id=selected_category_id,
                current_availability=availability,
                current_sort=sort,
                current_page=page,
                total_pages=total_pages,
                total_count=total_count,
                per_page=per_page,
            ),
        )

    @router.get("/store/categories/{category_id}", response_class=HTMLResponse)
    async def public_store_category_page(request: Request, category_id: int, availability: str = "", sort: str = "newest", page: int = 1):
        page = max(page, 1)
        per_page = 12

        async with async_session() as session:
            app_config = await get_app_config_view(session)
            categories = list((await session.execute(
                select(Category).where(Category.is_active == True).order_by(Category.name.asc())
            )).scalars().all())
            current_category = await session.get(Category, category_id)
            if not current_category or not current_category.is_active:
                return templates.TemplateResponse(
                    request,
                    "public_store.html",
                    _public_layout_context(
                        app_config,
                        page_title="Danh mục không tồn tại",
                        products=[],
                        categories=categories,
                        current_query="",
                        selected_category_id=None,
                        current_page=1,
                        total_pages=1,
                        total_count=0,
                        per_page=per_page,
                    ),
                    status_code=404,
                )

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
                select(Product, func.coalesce(stock_subquery.c.stock, 0).label("stock"), Category)
                .join(Category, Category.id == Product.category_id)
                .outerjoin(stock_subquery, stock_subquery.c.product_id == Product.id)
                .where(Product.is_active == True, Category.is_active == True, Product.category_id == category_id)
            )
            if availability == "in_stock":
                product_query = product_query.where(
                    or_(Product.delivery_mode == "fixed_content", func.coalesce(stock_subquery.c.stock, 0) > 0)
                )
            count_query = select(func.count()).select_from(product_query.order_by(None).subquery())
            total_count = await session.scalar(count_query) or 0
            total_pages = max((total_count + per_page - 1) // per_page, 1)
            if page > total_pages:
                page = total_pages

            rows = (await session.execute(
                _apply_store_sort(product_query, sort, stock_subquery)
                .offset((page - 1) * per_page)
                .limit(per_page)
            )).all()
            products = []
            for product, stock, category in rows:
                products.append(_product_card_payload(product, int(stock or 0), category))

        return templates.TemplateResponse(
            request,
            "public_store.html",
            _public_layout_context(
                app_config,
                page_title=f"Danh mục: {current_category.name}",
                products=products,
                categories=categories,
                current_query="",
                selected_category_id=current_category.id,
                current_availability=availability,
                current_sort=sort,
                current_page=page,
                total_pages=total_pages,
                total_count=total_count,
                per_page=per_page,
                current_category=current_category,
            ),
        )

    @router.get("/store/products/{product_id}", response_class=HTMLResponse)
    async def public_product_detail_page(request: Request, product_id: int):
        async with async_session() as session:
            app_config = await get_app_config_view(session)
            product = await session.get(Product, product_id)
            if not product or not product.is_active:
                return templates.TemplateResponse(
                    request,
                    "public_store_product.html",
                    _public_layout_context(
                        app_config,
                        page_title="Không tìm thấy sản phẩm",
                        product=None,
                    ),
                    status_code=404,
                )
            category = await session.get(Category, product.category_id)
            stock = await session.scalar(
                select(func.count(InventoryItem.id)).where(
                    InventoryItem.product_id == product.id,
                    InventoryItem.is_sold == False,
                )
            ) or 0

            related_stock_subquery = (
                select(
                    InventoryItem.product_id.label("product_id"),
                    func.count(InventoryItem.id).label("stock"),
                )
                .where(InventoryItem.is_sold == False)
                .group_by(InventoryItem.product_id)
                .subquery()
            )
            related_rows = (await session.execute(
                select(Product, func.coalesce(related_stock_subquery.c.stock, 0).label("stock"), Category)
                .join(Category, Category.id == Product.category_id)
                .outerjoin(related_stock_subquery, related_stock_subquery.c.product_id == Product.id)
                .where(
                    Product.is_active == True,
                    Category.is_active == True,
                    Product.category_id == product.category_id,
                    Product.id != product.id,
                )
                .order_by(Product.created_at.desc(), Product.id.desc())
                .limit(3)
            )).all()

        detail = _product_card_payload(product, int(stock or 0), category)
        related_products = [_product_card_payload(item, int(item_stock or 0), item_category) for item, item_stock, item_category in related_rows]
        return templates.TemplateResponse(
            request,
            "public_store_product.html",
            _public_layout_context(
                app_config,
                page_title=product.name,
                product=detail,
                related_products=related_products,
            ),
        )

    return router
