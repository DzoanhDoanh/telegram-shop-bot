from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import ceil

from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.models import SupportMessage, SupportTicket, SupportTicketStatus


@dataclass(slots=True)
class SupportTicketCreateResult:
    ticket: SupportTicket
    message: SupportMessage
    is_new_ticket: bool


@dataclass(slots=True)
class SupportTicketListSummary:
    total_count: int
    open_count: int
    admin_replied_count: int
    closed_count: int
    total_pages: int


async def get_open_ticket_for_user(session: AsyncSession, user_id: int) -> SupportTicket | None:
    result = await session.execute(
        select(SupportTicket)
        .where(
            SupportTicket.user_id == user_id,
            SupportTicket.status.in_([SupportTicketStatus.OPEN, SupportTicketStatus.ADMIN_REPLIED]),
        )
        .order_by(desc(SupportTicket.updated_at), desc(SupportTicket.id))
        .limit(1)
    )
    return result.scalars().first()


async def create_or_append_user_ticket(
    session: AsyncSession,
    user_id: int,
    content: str,
    telegram_message_id: int | None = None,
) -> SupportTicketCreateResult:
    ticket = await get_open_ticket_for_user(session, user_id)
    is_new_ticket = False
    if not ticket:
        ticket = SupportTicket(
            user_id=user_id,
            status=SupportTicketStatus.OPEN,
            subject="Yêu cầu hỗ trợ từ bot",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            last_user_message_at=datetime.utcnow(),
        )
        session.add(ticket)
        await session.flush()
        is_new_ticket = True

    ticket.status = SupportTicketStatus.OPEN
    ticket.updated_at = datetime.utcnow()
    ticket.last_user_message_at = datetime.utcnow()

    message = SupportMessage(
        ticket_id=ticket.id,
        sender_role="user",
        sender_user_id=user_id,
        content=content,
        telegram_message_id=telegram_message_id,
        created_at=datetime.utcnow(),
    )
    session.add(message)
    await session.commit()
    await session.refresh(ticket)
    await session.refresh(message)
    return SupportTicketCreateResult(ticket=ticket, message=message, is_new_ticket=is_new_ticket)


async def add_admin_reply(
    session: AsyncSession,
    ticket_id: int,
    admin_actor: str,
    content: str,
    telegram_message_id: int | None = None,
) -> tuple[SupportTicket | None, SupportMessage | None]:
    ticket = await session.get(SupportTicket, ticket_id)
    if not ticket:
        return None, None

    ticket.status = SupportTicketStatus.ADMIN_REPLIED
    ticket.updated_at = datetime.utcnow()
    ticket.last_admin_reply_at = datetime.utcnow()

    message = SupportMessage(
        ticket_id=ticket.id,
        sender_role="admin",
        sender_user_id=None,
        admin_actor=admin_actor,
        content=content,
        telegram_message_id=telegram_message_id,
        created_at=datetime.utcnow(),
    )
    session.add(message)
    await session.commit()
    await session.refresh(ticket)
    await session.refresh(message)
    return ticket, message


async def list_tickets(
    session: AsyncSession,
    status: str = "",
    q: str = "",
    page: int = 1,
    per_page: int = 30,
    sort: str = "updated_desc",
) -> tuple[list[SupportTicket], SupportTicketListSummary]:
    filters = []
    if status:
        try:
            filters.append(SupportTicket.status == SupportTicketStatus(status))
        except ValueError:
            pass
    if q.strip():
        keyword = q.strip()
        search_filters = [SupportTicket.subject.ilike(f"%{keyword}%")]
        if keyword.isdigit():
            search_filters.append(SupportTicket.user_id == int(keyword))
            search_filters.append(SupportTicket.id == int(keyword))
        filters.append(or_(*search_filters))

    total_count = await session.scalar(select(func.count(SupportTicket.id)).where(*filters)) or 0
    open_count = await session.scalar(select(func.count(SupportTicket.id)).where(SupportTicket.status == SupportTicketStatus.OPEN)) or 0
    admin_replied_count = await session.scalar(select(func.count(SupportTicket.id)).where(SupportTicket.status == SupportTicketStatus.ADMIN_REPLIED)) or 0
    closed_count = await session.scalar(select(func.count(SupportTicket.id)).where(SupportTicket.status == SupportTicketStatus.CLOSED)) or 0

    order_by_map = {
        "updated_asc": (SupportTicket.updated_at.asc(), SupportTicket.id.asc()),
        "created_desc": (SupportTicket.created_at.desc(), SupportTicket.id.desc()),
        "created_asc": (SupportTicket.created_at.asc(), SupportTicket.id.asc()),
        "id_asc": (SupportTicket.id.asc(),),
        "id_desc": (SupportTicket.id.desc(),),
        "updated_desc": (SupportTicket.updated_at.desc(), SupportTicket.id.desc()),
    }
    order_by = order_by_map.get(sort, order_by_map["updated_desc"])

    result = await session.execute(
        select(SupportTicket)
        .options(selectinload(SupportTicket.user), selectinload(SupportTicket.messages))
        .where(*filters)
        .order_by(*order_by)
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    summary = SupportTicketListSummary(
        total_count=total_count,
        open_count=open_count,
        admin_replied_count=admin_replied_count,
        closed_count=closed_count,
        total_pages=max(ceil(total_count / per_page), 1),
    )
    return list(result.scalars().all()), summary


async def get_ticket_detail(session: AsyncSession, ticket_id: int) -> SupportTicket | None:
    result = await session.execute(
        select(SupportTicket)
        .options(selectinload(SupportTicket.user), selectinload(SupportTicket.messages))
        .where(SupportTicket.id == ticket_id)
    )
    return result.scalars().first()


async def close_ticket(session: AsyncSession, ticket_id: int) -> SupportTicket | None:
    ticket = await session.get(SupportTicket, ticket_id)
    if not ticket:
        return None
    ticket.status = SupportTicketStatus.CLOSED
    ticket.updated_at = datetime.utcnow()
    await session.commit()
    await session.refresh(ticket)
    return ticket


async def reopen_ticket(session: AsyncSession, ticket_id: int) -> SupportTicket | None:
    ticket = await session.get(SupportTicket, ticket_id)
    if not ticket:
        return None
    ticket.status = SupportTicketStatus.OPEN
    ticket.updated_at = datetime.utcnow()
    await session.commit()
    await session.refresh(ticket)
    return ticket
