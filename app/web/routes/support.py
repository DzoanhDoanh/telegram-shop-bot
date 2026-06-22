from fastapi import APIRouter, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from app.database.session import async_session
from app.services import support_service
from app.web.audit import write_audit_event
from app.web.auth import get_admin_actor, validate_csrf_token

router = APIRouter()


def bind_routes(templates, template_context, is_authenticated, redirect_login, redirect_back, bot_getter):
    @router.get("/admin/support", response_class=HTMLResponse)
    async def support_tickets_page(request: Request, msg: str = "", status: str = "", q: str = "", sort: str = "updated_desc", page: int = 1):
        if not is_authenticated(request):
            return redirect_login()

        page = max(page, 1)
        per_page = 30
        async with async_session() as session:
            tickets, summary = await support_service.list_tickets(session, status=status, q=q, page=page, per_page=per_page, sort=sort)
            total_pages = summary.total_pages
            if page > total_pages:
                page = total_pages
                tickets, summary = await support_service.list_tickets(session, status=status, q=q, page=page, per_page=per_page, sort=sort)

        total_pages = summary.total_pages

        return templates.TemplateResponse(
            request,
            "support_tickets.html",
            template_context(
                request,
                active_page="support",
                tickets=tickets,
                msg=msg,
                current_status=status,
                current_query=q,
                current_page=page,
                total_pages=total_pages,
                total_count=summary.total_count,
                open_count=summary.open_count,
                admin_replied_count=summary.admin_replied_count,
                closed_count=summary.closed_count,
                current_sort=sort,
                per_page=per_page,
            ),
        )

    @router.get("/admin/support/{ticket_id}", response_class=HTMLResponse)
    async def support_ticket_detail_page(ticket_id: int, request: Request, msg: str = "", back: str = "/admin/support"):
        if not is_authenticated(request):
            return redirect_login()

        async with async_session() as session:
            ticket = await support_service.get_ticket_detail(session, ticket_id)
            if not ticket:
                return redirect_back("/admin/support", "Không tìm thấy ticket hỗ trợ")

        safe_back = back if back.startswith("/admin/support") else "/admin/support"
        return templates.TemplateResponse(
            request,
            "support_ticket_detail.html",
            template_context(request, active_page="support", ticket=ticket, msg=msg, back_url=safe_back),
        )

    @router.post("/admin/support/{ticket_id}/reply")
    async def support_ticket_reply(ticket_id: int, request: Request, csrf_token: str = Form(...), content: str = Form(...), close_after_reply: str = Form("0")):
        if not is_authenticated(request):
            return redirect_login()
        if not validate_csrf_token(request, csrf_token):
            return Response("CSRF token không hợp lệ", status_code=403)

        content = content.strip()
        if not content:
            return redirect_back(f"/admin/support/{ticket_id}", "Nội dung phản hồi không được để trống")

        actor = get_admin_actor(request)
        bot = bot_getter()
        should_close_after_reply = close_after_reply == "1"
        async with async_session() as session:
            ticket = await support_service.get_ticket_detail(session, ticket_id)
            if not ticket:
                return redirect_back("/admin/support", "Không tìm thấy ticket hỗ trợ")
            updated_ticket, _ = await support_service.add_admin_reply(session, ticket_id, actor, content)
            if updated_ticket and should_close_after_reply:
                updated_ticket = await support_service.close_ticket(session, ticket_id)

        if bot and updated_ticket:
            try:
                await bot.send_message(
                    chat_id=updated_ticket.user_id,
                    text=(
                        f"💬 <b>Phản hồi từ shop cho ticket #{updated_ticket.id}</b>\n\n"
                        f"{content}"
                    ),
                )
            except Exception:
                pass

        write_audit_event(request, "support_ticket_reply", ticket_id=ticket_id, actor=actor, close_after_reply=should_close_after_reply)
        success_message = "Đã gửi phản hồi và đóng ticket" if should_close_after_reply else "Đã gửi phản hồi cho người dùng"
        return redirect_back(f"/admin/support/{ticket_id}", success_message)

    @router.post("/admin/support/{ticket_id}/close")
    async def support_ticket_close(ticket_id: int, request: Request, csrf_token: str = Form(...)):
        if not is_authenticated(request):
            return redirect_login()
        if not validate_csrf_token(request, csrf_token):
            return Response("CSRF token không hợp lệ", status_code=403)

        async with async_session() as session:
            ticket = await support_service.close_ticket(session, ticket_id)
            if not ticket:
                return redirect_back("/admin/support", "Không tìm thấy ticket hỗ trợ")

        write_audit_event(request, "support_ticket_close", ticket_id=ticket_id)
        return redirect_back(f"/admin/support/{ticket_id}", "Đã đóng ticket hỗ trợ")

    @router.post("/admin/support/{ticket_id}/reopen")
    async def support_ticket_reopen(ticket_id: int, request: Request, csrf_token: str = Form(...)):
        if not is_authenticated(request):
            return redirect_login()
        if not validate_csrf_token(request, csrf_token):
            return Response("CSRF token không hợp lệ", status_code=403)

        async with async_session() as session:
            ticket = await support_service.reopen_ticket(session, ticket_id)
            if not ticket:
                return redirect_back("/admin/support", "Không tìm thấy ticket hỗ trợ")

        write_audit_event(request, "support_ticket_reopen", ticket_id=ticket_id)
        return redirect_back(f"/admin/support/{ticket_id}", "Đã mở lại ticket hỗ trợ")

    return router
