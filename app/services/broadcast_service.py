from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from aiogram import Bot
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import BroadcastCampaign, BroadcastCampaignStatus, User, WalletTransaction, WalletTxStatus, WalletTxType

logger = logging.getLogger(__name__)
DEFAULT_SEND_LIMIT = 200
PREVIEW_LIMIT = 20


@dataclass(slots=True)
class BroadcastRecipientsPreview:
    users: list[User]
    recipient_count: int


def segment_filter(segment: str):
    successful_depositor_ids = select(WalletTransaction.user_id).where(
        WalletTransaction.tx_type == WalletTxType.DEPOSIT,
        WalletTransaction.status == WalletTxStatus.SUCCESS,
    )
    if segment == "repeat_buyers":
        return User.total_spent > 0
    if segment == "deposit_no_purchase":
        return and_(User.id.in_(successful_depositor_ids), User.total_spent <= 0)
    if segment == "wallet_rich":
        return User.wallet_balance >= 200000
    if segment == "new_no_deposit":
        return and_(User.total_spent <= 0, ~User.id.in_(successful_depositor_ids))
    if segment == "vip":
        return User.total_spent >= 500000
    return None


async def preview_recipients(session: AsyncSession, segment: str, preview_limit: int = PREVIEW_LIMIT) -> BroadcastRecipientsPreview:
    query = select(User).where(User.is_banned == False).order_by(User.created_at.desc(), User.id.desc())
    current_filter = segment_filter(segment)
    if current_filter is not None:
        query = query.where(current_filter)
    users = list((await session.execute(query.limit(preview_limit))).scalars().all())
    recipient_count = await session.scalar(select(func.count(User.id)).select_from(query.order_by(None).subquery())) or 0
    return BroadcastRecipientsPreview(users=users, recipient_count=int(recipient_count))


async def send_broadcast_campaign(
    session: AsyncSession,
    bot: Bot,
    *,
    segment: str,
    message: str,
    admin_actor: str | None,
    send_limit: int = DEFAULT_SEND_LIMIT,
) -> BroadcastCampaign:
    clean_message = message.strip()
    if not clean_message:
        raise ValueError("Nội dung broadcast không được để trống")
    send_limit = max(1, min(int(send_limit or DEFAULT_SEND_LIMIT), 500))

    preview = await preview_recipients(session, segment, preview_limit=send_limit)
    campaign = BroadcastCampaign(
        segment=segment,
        message=clean_message,
        recipient_count=preview.recipient_count,
        admin_actor=admin_actor,
        status=BroadcastCampaignStatus.DRAFT,
        notes=f"Giới hạn gửi mỗi đợt: {send_limit}",
    )
    session.add(campaign)
    await session.flush()

    sent_count = 0
    failed_count = 0
    for user in preview.users:
        try:
            await bot.send_message(chat_id=user.id, text=clean_message)
            sent_count += 1
        except Exception:
            failed_count += 1
            logger.exception("Failed to send broadcast", extra={"campaign_id": campaign.id, "user_id": user.id})

    campaign.sent_count = sent_count
    campaign.failed_count = failed_count
    campaign.sent_at = datetime.utcnow()
    if sent_count <= 0:
        campaign.status = BroadcastCampaignStatus.FAILED
    elif failed_count > 0:
        campaign.status = BroadcastCampaignStatus.PARTIAL
    else:
        campaign.status = BroadcastCampaignStatus.SENT

    await session.commit()
    await session.refresh(campaign)
    return campaign


async def list_recent_campaigns(session: AsyncSession, limit: int = 20) -> list[BroadcastCampaign]:
    result = await session.execute(
        select(BroadcastCampaign).order_by(BroadcastCampaign.created_at.desc(), BroadcastCampaign.id.desc()).limit(limit)
    )
    return list(result.scalars().all())
