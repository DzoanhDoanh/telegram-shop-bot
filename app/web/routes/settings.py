from fastapi import APIRouter, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from app.config import settings
from app.database.session import async_session
from app.services import app_config_service
from app.web.auth import validate_csrf_token
from app.web.audit import write_audit_event

router = APIRouter()


def bind_routes(
    templates,
    template_context,
    is_authenticated,
    redirect_login,
    redirect_back,
):
    @router.get("/admin/settings", response_class=HTMLResponse)
    async def settings_page(request: Request, msg: str = ""):
        if not is_authenticated(request):
            return redirect_login()

        async with async_session() as session:
            config = await app_config_service.ensure_app_config(session)
            await session.commit()
            app_view = app_config_service.to_view(config)

        return templates.TemplateResponse(
            request,
            "settings.html",
            template_context(
                request,
                active_page="settings",
                msg=msg,
                app_config=app_view,
            ),
        )

    @router.post("/admin/settings")
    async def update_settings_page(
        request: Request,
        csrf_token: str = Form(...),
        shop_display_name: str = Form(""),
        support_username: str = Form(""),
        welcome_text: str = Form(""),
        help_text: str = Form(""),
        terms_text: str = Form(""),
        support_text: str = Form(""),
        maintenance_mode: str = Form("off"),
        enable_product_search: str = Form("off"),
        enable_support_forwarding: str = Form("off"),
        enable_lucky_spin: str = Form("off"),
        show_terms_button: str = Form("off"),
        show_help_button: str = Form("off"),
    ):
        if not is_authenticated(request):
            return redirect_login()
        if not validate_csrf_token(request, csrf_token):
            return Response("CSRF token không hợp lệ", status_code=403)

        async with async_session() as session:
            config = await app_config_service.ensure_app_config(session)
            config.shop_display_name = shop_display_name.strip() or settings.SHOP_NAME
            config.support_username = support_username.strip().lstrip("@") or None
            config.welcome_text = welcome_text.strip() or app_config_service.DEFAULT_WELCOME_TEXT
            config.help_text = help_text.strip() or app_config_service.DEFAULT_HELP_TEXT
            config.terms_text = terms_text.strip() or app_config_service.DEFAULT_TERMS_TEXT
            config.support_text = support_text.strip() or app_config_service.DEFAULT_SUPPORT_TEXT
            config.maintenance_mode = maintenance_mode == "on"
            config.enable_product_search = enable_product_search == "on"
            config.enable_support_forwarding = enable_support_forwarding == "on"
            config.enable_lucky_spin = enable_lucky_spin == "on"
            config.show_terms_button = show_terms_button == "on"
            config.show_help_button = show_help_button == "on"
            config.is_active = True
            await session.commit()

        write_audit_event(request, "update_app_config")
        return redirect_back("/admin/settings", "Đã lưu cấu hình bot/shop")

    return router
