from urllib.parse import quote

from fastapi import APIRouter, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from app.database.session import async_session
from app.services import broadcast_service
from app.web.audit import write_audit_event
from app.web.auth import get_admin_actor, validate_csrf_token

router = APIRouter()


def bind_routes(templates, template_context, is_authenticated, redirect_login, bot_getter):
    @router.get("/admin/broadcasts", response_class=HTMLResponse)
    async def broadcasts_page(request: Request, segment: str = "all", message: str = "", msg: str = ""):
        if not is_authenticated(request):
            return redirect_login()

        async with async_session() as session:
            preview = await broadcast_service.preview_recipients(session, segment)
            recent_campaigns = await broadcast_service.list_recent_campaigns(session)

        return templates.TemplateResponse(
            request,
            "broadcasts.html",
            template_context(
                request,
                active_page="broadcasts",
                current_segment=segment,
                draft_message=message,
                preview_users=preview.users,
                recipient_count=preview.recipient_count,
                recent_campaigns=recent_campaigns,
                msg=msg,
            ),
        )

    @router.post("/admin/broadcasts/preview", response_class=HTMLResponse)
    async def broadcasts_preview(
        request: Request,
        csrf_token: str = Form(...),
        segment: str = Form("all"),
        message: str = Form(""),
    ):
        if not is_authenticated(request):
            return redirect_login()
        if not validate_csrf_token(request, csrf_token):
            return Response("CSRF token không hợp lệ", status_code=403)

        async with async_session() as session:
            preview = await broadcast_service.preview_recipients(session, segment)
            recent_campaigns = await broadcast_service.list_recent_campaigns(session)

        return templates.TemplateResponse(
            request,
            "broadcasts.html",
            template_context(
                request,
                active_page="broadcasts",
                current_segment=segment,
                draft_message=message,
                preview_users=preview.users,
                recipient_count=preview.recipient_count,
                recent_campaigns=recent_campaigns,
                msg="Đã cập nhật preview broadcast. Chưa gửi tin nhắn thật.",
            ),
        )

    @router.post("/admin/broadcasts/send")
    async def broadcasts_send(
        request: Request,
        csrf_token: str = Form(...),
        segment: str = Form("all"),
        message: str = Form(""),
        send_limit: int = Form(200),
    ):
        if not is_authenticated(request):
            return redirect_login()
        if not validate_csrf_token(request, csrf_token):
            return Response("CSRF token không hợp lệ", status_code=403)

        clean_message = message.strip()
        if not clean_message:
            return RedirectResponse("/admin/broadcasts?msg=Nội dung broadcast không được để trống", status_code=302)

        bot = bot_getter()
        if not bot:
            return RedirectResponse("/admin/broadcasts?msg=Bot chưa sẵn sàng để gửi broadcast", status_code=302)

        actor = get_admin_actor(request)
        async with async_session() as session:
            campaign = await broadcast_service.send_broadcast_campaign(
                session,
                bot,
                segment=segment,
                message=clean_message,
                admin_actor=actor,
                send_limit=send_limit,
            )

        write_audit_event(
            request,
            "broadcast_send",
            actor=actor,
            campaign_id=campaign.id,
            segment=segment,
            recipient_count=campaign.recipient_count,
            sent_count=campaign.sent_count,
            failed_count=campaign.failed_count,
            status=campaign.status.value,
        )
        msg = quote(
            f"Đã tạo chiến dịch broadcast #{campaign.id}: gửi thành công {campaign.sent_count}/{campaign.recipient_count}, lỗi {campaign.failed_count}."
        )
        return RedirectResponse(
            f"/admin/broadcasts?segment={quote(segment)}&message={quote(clean_message)}&msg={msg}",
            status_code=302,
        )

    return router
