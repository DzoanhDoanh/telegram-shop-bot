from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.models import AppConfig


@dataclass(slots=True)
class AppConfigView:
    shop_display_name: str
    support_username: str
    welcome_text: str
    help_text: str
    terms_text: str
    support_text: str
    maintenance_mode: bool
    enable_product_search: bool
    enable_support_forwarding: bool
    enable_lucky_spin: bool
    show_terms_button: bool
    show_help_button: bool


DEFAULT_WELCOME_TEXT = (
    "Shop bán sản phẩm số theo mô hình <b>ví điện tử trước, giao hàng tự động sau</b>.\n\n"
    "Luồng nhanh nhất: <b>Nạp ví → đợi hệ thống cộng tiền → chọn sản phẩm → bot giao hàng tự động ngay trong Telegram</b>.\n\n"
    "Bấm 🛍 Mua hàng để xem danh mục, hoặc ❓ Hướng dẫn nếu đây là lần đầu bạn mua."
)

DEFAULT_HELP_TEXT = (
    "❓ <b>Hướng dẫn mua hàng</b>\n\n"
    "1. Vào <b>💰 Ví của tôi</b> và tạo yêu cầu nạp ví.\n"
    "2. Chuyển khoản <b>đúng số tiền</b> và <b>đúng mã nạp</b> mà bot đã tạo.\n"
    "3. Hệ thống sẽ tự kiểm tra giao dịch và cộng số dư ví cho bạn.\n"
    "4. Sau khi ví đã có tiền, chọn sản phẩm cần mua và xác nhận thanh toán.\n"
    "5. Bot sẽ tự giao sản phẩm số ngay trong Telegram nếu đơn thành công.\n\n"
    "Nếu chuyển khoản sai nội dung, webhook chậm, hoặc có sự cố ngoài ý muốn, hãy bấm 💬 Hỗ trợ. Gửi bill thủ công chỉ là phương án dự phòng khi shop cần kiểm tra.\n\n"
    "Bạn có thể gõ <code>/terms</code> để xem điều khoản mua hàng và chính sách hỗ trợ."
)

DEFAULT_TERMS_TEXT = (
    "📜 <b>Điều khoản mua hàng</b>\n\n"
    "1. Shop cung cấp <b>sản phẩm số</b>, phần lớn được giao tự động ngay trong Telegram sau khi thanh toán thành công.\n"
    "2. Người mua phải chuyển khoản <b>đúng số tiền</b> và <b>đúng mã nạp</b> mà bot cung cấp. Chuyển sai nội dung vui lòng liên hệ shop để được hỗ trợ.\n"
    "3. Sau khi thanh toán thành công, bot sẽ giao đúng nội dung sản phẩm tương ứng ngay trong Telegram.\n"
    "4. Sau khi sản phẩm số đã giao thành công, shop chỉ hỗ trợ các lỗi hợp lệ như giao thiếu, giao sai, hoặc sự cố hệ thống có thể xác minh.\n"
    "5. Shop <b>không hoàn tiền tùy ý</b> đối với các trường hợp người dùng đổi ý sau khi đã nhận đúng sản phẩm số, trừ khi admin xác nhận có lỗi từ hệ thống hoặc từ phía shop.\n"
    "6. Nếu cần hỗ trợ, hãy bấm <b>💬 Hỗ trợ</b> hoặc gõ <code>/support</code> và gửi kèm mã đơn hàng nếu có.\n"
    "7. Shop có quyền từ chối phục vụ hoặc khóa tài khoản đối với hành vi gian lận, lạm dụng, spam hoặc cố tình gây rối hệ thống."
)

DEFAULT_SUPPORT_TEXT = (
    "💬 <b>Hỗ trợ khách hàng</b>\n\n"
    "Hãy gửi nội dung bạn cần hỗ trợ ở tin nhắn tiếp theo.\n"
    "Nếu liên quan đến đơn hàng, vui lòng ghi kèm mã đơn hàng để shop kiểm tra nhanh hơn.\n\n"
    "Gõ <code>/cancel</code> nếu muốn hủy."
)


async def get_app_config(session: AsyncSession) -> AppConfig | None:
    return await session.scalar(
        select(AppConfig)
        .where(AppConfig.is_active == True)
        .order_by(AppConfig.id.desc())
        .limit(1)
    )


async def ensure_app_config(session: AsyncSession) -> AppConfig:
    config = await get_app_config(session)
    if config:
        return config
    config = AppConfig(
        shop_display_name=settings.SHOP_NAME,
        support_username=(settings.SHOP_SUPPORT_USERNAME or "").strip().lstrip("@") or None,
        welcome_text=DEFAULT_WELCOME_TEXT,
        help_text=DEFAULT_HELP_TEXT,
        terms_text=DEFAULT_TERMS_TEXT,
        support_text=DEFAULT_SUPPORT_TEXT,
        is_active=True,
    )
    session.add(config)
    await session.flush()
    return config


def to_view(config: AppConfig | None) -> AppConfigView:
    support_username = ((config.support_username if config else None) or settings.SHOP_SUPPORT_USERNAME or "").strip().lstrip("@")
    shop_name = ((config.shop_display_name if config else None) or settings.SHOP_NAME or "Digital Shop").strip()
    return AppConfigView(
        shop_display_name=shop_name,
        support_username=support_username,
        welcome_text=((config.welcome_text if config else None) or DEFAULT_WELCOME_TEXT).strip(),
        help_text=((config.help_text if config else None) or DEFAULT_HELP_TEXT).strip(),
        terms_text=((config.terms_text if config else None) or DEFAULT_TERMS_TEXT).strip(),
        support_text=((config.support_text if config else None) or DEFAULT_SUPPORT_TEXT).strip(),
        maintenance_mode=bool(config.maintenance_mode) if config else False,
        enable_product_search=True if config is None else bool(config.enable_product_search),
        enable_support_forwarding=True if config is None else bool(config.enable_support_forwarding),
        enable_lucky_spin=True if config is None else bool(config.enable_lucky_spin),
        show_terms_button=True if config is None else bool(config.show_terms_button),
        show_help_button=True if config is None else bool(config.show_help_button),
    )


async def get_app_config_view(session: AsyncSession) -> AppConfigView:
    config = await ensure_app_config(session)
    return to_view(config)
