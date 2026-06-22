from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.config import settings
from app.web.audit import client_ip, write_audit_event

router = APIRouter()


def bind_routes(templates, is_authenticated, set_admin_session, clear_admin_session, login_limited, record_login_failure, login_failures):
    @router.get("/login", response_class=HTMLResponse)
    async def get_login(request: Request):
        if is_authenticated(request):
            return RedirectResponse("/admin", status_code=302)
        return templates.TemplateResponse(request, "login.html", {"active_page": ""})

    @router.post("/login")
    async def post_login(request: Request, password: str = Form(...)):
        ip = client_ip(request)

        if login_limited(ip):
            write_audit_event(request, "login_rate_limited")
            return templates.TemplateResponse(request, "login.html", {
                "active_page": "",
                "error": "Quá nhiều lần đăng nhập thất bại. Vui lòng thử lại sau."
            })

        if password == settings.ADMIN_PASSWORD:
            actor = f"admin@{ip}"
            write_audit_event(request, "login_success", actor=actor)
            login_failures.pop(ip, None)
            response = RedirectResponse("/admin", status_code=302)
            set_admin_session(response, actor)
            return response

        write_audit_event(request, "login_failed")
        record_login_failure(ip)
        return templates.TemplateResponse(request, "login.html", {
            "active_page": "",
            "error": "Mật khẩu không đúng. Vui lòng thử lại."
        })

    @router.get("/logout")
    async def logout(request: Request):
        write_audit_event(request, "logout")
        response = RedirectResponse("/login", status_code=302)
        clear_admin_session(response)
        return response

    return router
