from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import LuckySpinLog, LuckySpinResultType, User, Voucher, VoucherDiscountType, WalletTxType
from app.services import voucher_service, wallet_service

SPIN_COOLDOWN_HOURS = 24

REWARD_POOL = [
    {"label": "1.000đ vào ví", "type": LuckySpinResultType.WALLET_CREDIT, "amount": Decimal("1000")},
    {"label": "2.000đ vào ví", "type": LuckySpinResultType.WALLET_CREDIT, "amount": Decimal("2000")},
    {"label": "5.000đ vào ví", "type": LuckySpinResultType.WALLET_CREDIT, "amount": Decimal("5000")},
    {"label": "Voucher giảm 10%", "type": LuckySpinResultType.VOUCHER, "voucher_percent": Decimal("10")},
    {"label": "Quà bí mật", "type": LuckySpinResultType.TEXT, "note": "Liên hệ shop để nhận quà bí mật hôm nay."},
    {"label": "Chúc bạn may mắn lần sau", "type": LuckySpinResultType.TEXT, "note": "Bạn chưa nhận được thưởng thật ở lượt này."},
]


@dataclass(slots=True)
class LuckySpinOutcome:
    ok: bool
    message: str
    reward_label: str = ""
    reward_type: str = ""
    wallet_amount: Decimal = Decimal("0")
    voucher_code: str | None = None
    next_available_at: datetime | None = None


def reward_preview_labels() -> list[str]:
    return [item["label"] for item in REWARD_POOL]


async def get_latest_spin(session: AsyncSession, user_id: int) -> LuckySpinLog | None:
    return await session.scalar(
        select(LuckySpinLog)
        .where(LuckySpinLog.user_id == user_id)
        .order_by(LuckySpinLog.created_at.desc(), LuckySpinLog.id.desc())
        .limit(1)
    )


async def spin_once(session: AsyncSession, user_id: int) -> LuckySpinOutcome:
    user = await session.get(User, user_id, with_for_update=True)
    if not user:
        return LuckySpinOutcome(False, "Không tìm thấy người dùng.")

    latest_spin = await get_latest_spin(session, user_id)
    now = datetime.utcnow()
    if latest_spin and latest_spin.created_at:
        next_available_at = latest_spin.created_at + timedelta(hours=SPIN_COOLDOWN_HOURS)
        if next_available_at > now:
            return LuckySpinOutcome(
                False,
                "Bạn đã dùng lượt quay hôm nay. Hãy quay lại sau nhé.",
                next_available_at=next_available_at,
            )

    reward = random.choice(REWARD_POOL)
    reward_type: LuckySpinResultType = reward["type"]
    reward_label = str(reward["label"])
    wallet_amount = Decimal("0")
    voucher_code = None
    note = reward.get("note")

    if reward_type == LuckySpinResultType.WALLET_CREDIT:
        wallet_amount = Decimal(str(reward["amount"]))
        result = await wallet_service.adjust_wallet_balance(
            session,
            user_id,
            wallet_amount,
            WalletTxType.ADMIN_CREDIT,
            "lucky_spin",
            f"Thưởng vòng quay may mắn: {reward_label}",
        )
        if not result.success:
            return LuckySpinOutcome(False, result.message)
    elif reward_type == LuckySpinResultType.VOUCHER:
        voucher_code = f"SPIN{user_id}{int(now.timestamp())}"[-16:]
        voucher = Voucher(
            code=voucher_code.upper(),
            name="Voucher từ vòng quay may mắn",
            description="Voucher retention từ lucky spin",
            discount_type=VoucherDiscountType.PERCENT,
            discount_value=float(Decimal(str(reward["voucher_percent"]))),
            min_order_amount=0,
            usage_limit=1,
            used_count=0,
            is_active=True,
            starts_at=now,
            expires_at=now + timedelta(days=3),
        )
        session.add(voucher)
        await session.flush()
        voucher_code = voucher_service.normalize_code(voucher.code)

    spin_log = LuckySpinLog(
        user_id=user_id,
        reward_label=reward_label,
        result_type=reward_type,
        reward_amount=float(wallet_amount) if wallet_amount > 0 else None,
        voucher_code=voucher_code,
        note=note,
    )
    session.add(spin_log)
    await session.commit()
    return LuckySpinOutcome(
        True,
        "Quay thành công.",
        reward_label=reward_label,
        reward_type=reward_type.value,
        wallet_amount=wallet_amount,
        voucher_code=voucher_code,
        next_available_at=now + timedelta(hours=SPIN_COOLDOWN_HOURS),
    )
