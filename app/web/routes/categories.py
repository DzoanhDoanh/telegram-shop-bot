from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select

from app.database.models import Category, Product
from app.database.session import async_session
from app.web.audit import write_audit_event
from app.web.auth import validate_csrf_token

router = APIRouter()


def bind_routes(templates, template_context, is_authenticated, redirect_login):
    @router.get("/admin/categories", response_class=HTMLResponse)
    async def categories_page(request: Request, msg: str = ""):
        if not is_authenticated(request):
            return redirect_login()

        async with async_session() as session:
            result = await session.execute(
                select(Category, func.count(Product.id).label("product_count"))
                .outerjoin(
                    Product,
                    (Product.category_id == Category.id) & (Product.is_active == True),
                )
                .where(Category.is_active == True)
                .group_by(Category.id)
                .order_by(Category.name.asc())
            )
            categories = [
                {
                    "id": category.id,
                    "name": category.name,
                    "description": category.description,
                    "emoji": category.emoji,
                    "product_count": product_count,
                }
                for category, product_count in result.all()
            ]

        return templates.TemplateResponse(
            request,
            "categories.html",
            template_context(request, active_page="categories", categories=categories, msg=msg),
        )

    @router.post("/admin/categories/add")
    async def add_category_web(
        request: Request,
        name: str = Form(...),
        description: str = Form(""),
        emoji: str = Form("📦"),
        csrf_token: str = Form(...),
    ):
        if not is_authenticated(request):
            return redirect_login()
        if not validate_csrf_token(request, csrf_token):
            return RedirectResponse('/login', status_code=302)

        category_name = name.strip()
        if not category_name:
            return RedirectResponse("/admin/categories?msg=Tên danh mục không được để trống", status_code=302)

        async with async_session() as session:
            existing = await session.scalar(
                select(Category).where(
                    func.lower(Category.name) == category_name.lower(),
                    Category.is_active == True,
                )
            )
            if existing:
                return RedirectResponse("/admin/categories?msg=Danh mục này đã tồn tại", status_code=302)

            category = Category(
                name=category_name,
                description=description.strip() or None,
                emoji=(emoji.strip() or "📦")[:10],
                is_active=True,
            )
            session.add(category)
            await session.commit()
            await session.refresh(category)

        write_audit_event(request, "category_add", category_id=category.id, name=category_name)
        return RedirectResponse(f"/admin/categories?msg=Đã tạo danh mục '{category_name}'", status_code=302)

    @router.post("/admin/categories/{category_id}/edit")
    async def edit_category_web(
        category_id: int,
        request: Request,
        name: str = Form(...),
        description: str = Form(""),
        emoji: str = Form("📦"),
        csrf_token: str = Form(...),
    ):
        if not is_authenticated(request):
            return redirect_login()
        if not validate_csrf_token(request, csrf_token):
            return RedirectResponse('/login', status_code=302)

        category_name = name.strip()
        if not category_name:
            return RedirectResponse("/admin/categories?msg=Tên danh mục không được để trống", status_code=302)

        async with async_session() as session:
            category = await session.scalar(
                select(Category).where(Category.id == category_id, Category.is_active == True)
            )
            if not category:
                return RedirectResponse("/admin/categories?msg=Danh mục không tồn tại", status_code=302)

            duplicate = await session.scalar(
                select(Category).where(
                    Category.id != category_id,
                    func.lower(Category.name) == category_name.lower(),
                    Category.is_active == True,
                )
            )
            if duplicate:
                return RedirectResponse("/admin/categories?msg=Danh mục này đã tồn tại", status_code=302)

            category.name = category_name
            category.description = description.strip() or None
            category.emoji = (emoji.strip() or "📦")[:10]
            await session.commit()

        write_audit_event(request, "category_edit", category_id=category_id, name=category_name)
        return RedirectResponse(f"/admin/categories?msg=Đã cập nhật danh mục '{category_name}'", status_code=302)

    @router.post("/admin/categories/{category_id}/delete")
    async def delete_category_web(category_id: int, request: Request, csrf_token: str = Form(...)):
        if not is_authenticated(request):
            return redirect_login()
        if not validate_csrf_token(request, csrf_token):
            return RedirectResponse('/login', status_code=302)

        async with async_session() as session:
            category = await session.scalar(
                select(Category).where(Category.id == category_id, Category.is_active == True)
            )
            if not category:
                return RedirectResponse("/admin/categories?msg=Danh mục không tồn tại", status_code=302)

            active_products = await session.scalar(
                select(func.count(Product.id)).where(
                    Product.category_id == category_id,
                    Product.is_active == True,
                )
            ) or 0
            if active_products > 0:
                return RedirectResponse(
                    "/admin/categories?msg=Không thể xóa danh mục đang có sản phẩm. Hãy chuyển hoặc xóa sản phẩm trước.",
                    status_code=302,
                )

            category_name = category.name
            category.is_active = False
            await session.commit()

        write_audit_event(request, "category_delete", category_id=category_id, name=category_name)
        return RedirectResponse(f"/admin/categories?msg=Đã xóa danh mục '{category_name}'", status_code=302)

    return router
