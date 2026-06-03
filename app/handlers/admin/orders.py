from aiogram import Router, F, types
from app.database.session import async_session
from app.services import order_service, delivery_service
from app.config import settings

router = Router()

@router.callback_query(F.data.startswith("admin_approve_"))
async def admin_approve_order(callback: types.CallbackQuery):
    if callback.from_user.id not in settings.ADMIN_IDS:
        await callback.answer("Bạn không có quyền thực hiện hành động này.", show_alert=True)
        return

    order_id = int(callback.data.split("_")[2])
    
    async with async_session() as session:
        result = await delivery_service.approve_and_deliver_order(session, callback.bot, order_id)

    caption = callback.message.caption or ""
    if result.success:
        await callback.message.edit_caption(caption=caption + f"\n\n✅ {result.message}")
        await callback.answer("Đã duyệt đơn hàng thành công!")
    else:
        await callback.message.edit_caption(caption=caption + f"\n\n⚠️ {result.message}")
        await callback.answer(result.message, show_alert=True)

@router.callback_query(F.data.startswith("admin_reject_"))
async def admin_reject_order(callback: types.CallbackQuery):
    if callback.from_user.id not in settings.ADMIN_IDS:
        await callback.answer("Bạn không có quyền thực hiện hành động này.", show_alert=True)
        return

    order_id = int(callback.data.split("_")[2])
    
    async with async_session() as session:
        order = await order_service.reject_order(session, order_id)
        if not order:
            await callback.answer("Đơn hàng không tồn tại hoặc đã được xử lý.")
            return
            
        try:
            await callback.bot.send_message(
                chat_id=order.user_id,
                text=f"❌ Đơn hàng #{order.id} của bạn đã bị từ chối. Vui lòng liên hệ hỗ trợ nếu bạn đã thanh toán."
            )
        except Exception:
            pass
            
        caption = callback.message.caption or ""
        await callback.message.edit_caption(caption=caption + f"\n\n❌ Đã từ chối đơn hàng.")
        await callback.answer("Đã từ chối đơn hàng.")
