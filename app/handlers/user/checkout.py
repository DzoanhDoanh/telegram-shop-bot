from aiogram import F, Router, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.database.models import User
from app.database.session import async_session
from app.services import product_service, wallet_service

router = Router()


class QuantityInputState(StatesGroup):
    waiting_for_quantity = State()


def _fail_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Nạp tiền vào ví", callback_data="wallet_deposit")],
        [InlineKeyboardButton(text="Xem sản phẩm khác", callback_data="shop_catalog")],
    ])


def _success_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Mua thêm", callback_data="shop_catalog")],
        [InlineKeyboardButton(text="Xem ví", callback_data="wallet_home")],
        [InlineKeyboardButton(text="Xem đơn hàng", callback_data="shop_orders")],
    ])


def _clamp_quantity(product, stock: int, requested_quantity: int) -> int:
    if not getattr(product, "allow_quantity_selection", False):
        return 1
    minimum = max(1, int(getattr(product, "min_quantity", 1) or 1))
    maximum = max(minimum, int(getattr(product, "max_quantity", minimum) or minimum))
    return max(minimum, min(requested_quantity, maximum, max(stock, 1)))


def _quantity_keyboard(product, stock: int, quantity: int) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []
    if stock > 0 and getattr(product, "allow_quantity_selection", False):
        row: list[InlineKeyboardButton] = []
        if quantity > max(1, int(product.min_quantity or 1)):
            row.append(InlineKeyboardButton(text="➖ Giảm", callback_data=f"qty_{product.id}_{quantity - 1}"))
        if quantity < min(stock, max(int(product.max_quantity or 1), int(product.min_quantity or 1))):
            row.append(InlineKeyboardButton(text="➕ Tăng", callback_data=f"qty_{product.id}_{quantity + 1}"))
        if row:
            buttons.append(row)
        buttons.append([InlineKeyboardButton(text="⌨️ Nhập số lượng", callback_data=f"qtyinput_{product.id}")])
    buttons.append([InlineKeyboardButton(text="Xác nhận mua", callback_data=f"purchase_{product.id}_{quantity}")])
    buttons.append([InlineKeyboardButton(text="Hủy", callback_data=f"prod_{product.id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def _render_confirmation(callback: types.CallbackQuery, product_id: int, requested_quantity: int | None = None):
    user_id = callback.from_user.id

    async with async_session() as session:
        user = await session.get(User, user_id)
        if not user or user.is_banned:
            await callback.answer("Tài khoản không hợp lệ hoặc đã bị cấm.", show_alert=True)
            return

        product = await product_service.get_product(session, product_id)
        if not product or not product.is_active:
            await callback.answer("Sản phẩm không tồn tại hoặc đã ngừng bán.", show_alert=True)
            return

        stock = await product_service.get_stock_count(session, product_id)
        if stock <= 0:
            await callback.answer("Sản phẩm đã hết hàng.", show_alert=True)
            return

        default_quantity = int(product.min_quantity or 1) if product.allow_quantity_selection else 1
        quantity = _clamp_quantity(product, stock, requested_quantity or default_quantity)
        price = wallet_service.money(product.price)
        total_price = wallet_service.money(price * quantity)
        balance = wallet_service.money(user.wallet_balance)

    quantity_note = "Khách không thể đổi số lượng cho sản phẩm này." if not product.allow_quantity_selection else (
        f"Bạn có thể chọn từ <b>{int(product.min_quantity or 1)}</b> đến <b>{min(stock, max(int(product.max_quantity or 1), int(product.min_quantity or 1)))}</b> sản phẩm hoặc bấm nút nhập số lượng để gõ trực tiếp."
    )

    await callback.message.edit_text(
        "🧾 <b>Xác nhận mua hàng</b>\n\n"
        f"Sản phẩm: <b>{product.name}</b>\n"
        f"Đơn giá: <b>{wallet_service.format_vnd(price)}</b>\n"
        f"Số lượng: <b>{quantity}</b>\n"
        f"Tổng tiền: <b>{wallet_service.format_vnd(total_price)}</b>\n"
        f"Tồn kho hiện tại: <b>{stock}</b>\n"
        f"Số dư hiện tại: <b>{wallet_service.format_vnd(balance)}</b>\n\n"
        f"{quantity_note}\n\n"
        "Nếu xác nhận, hệ thống sẽ trừ tiền trong ví và giao đúng số lượng hàng tự động.",
        reply_markup=_quantity_keyboard(product, stock, quantity),
    )


@router.callback_query(F.data.startswith("buy_"))
async def confirm_purchase(callback: types.CallbackQuery, state: FSMContext):
    product_id = int(callback.data.split("_")[1])
    await state.clear()
    await _render_confirmation(callback, product_id)
    await callback.answer()


@router.callback_query(F.data.startswith("qty_"))
async def update_purchase_quantity(callback: types.CallbackQuery):
    _, product_id, quantity = callback.data.split("_")
    await _render_confirmation(callback, int(product_id), int(quantity))
    await callback.answer()


@router.callback_query(F.data.startswith("qtyinput_"))
async def request_quantity_input(callback: types.CallbackQuery, state: FSMContext):
    product_id = int(callback.data.split("_")[1])

    async with async_session() as session:
        product = await product_service.get_product(session, product_id)
        if not product or not product.is_active:
            await callback.answer("Sản phẩm không tồn tại hoặc đã ngừng bán.", show_alert=True)
            return
        stock = await product_service.get_stock_count(session, product_id)
        if stock <= 0:
            await callback.answer("Sản phẩm đã hết hàng.", show_alert=True)
            return
        minimum = max(1, int(product.min_quantity or 1))
        maximum = min(stock, max(int(product.max_quantity or 1), minimum))

    await state.set_state(QuantityInputState.waiting_for_quantity)
    await state.update_data(product_id=product_id)
    await callback.message.answer(
        "⌨️ <b>Nhập số lượng muốn mua</b>\n\n"
        f"Sản phẩm: <b>{product.name}</b>\n"
        f"Bạn có thể nhập từ <b>{minimum}</b> đến <b>{maximum}</b>.\n"
        "Ví dụ: <code>3</code>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Hủy nhập", callback_data=f"prod_{product_id}")]
        ]),
    )
    await callback.answer()


@router.message(QuantityInputState.waiting_for_quantity)
async def handle_quantity_input(message: types.Message, state: FSMContext):
    raw_text = (message.text or "").strip()
    if not raw_text.isdigit():
        await message.answer("Vui lòng nhập một số nguyên hợp lệ. Ví dụ: <code>2</code>.")
        return

    requested_quantity = int(raw_text)
    data = await state.get_data()
    product_id = data.get("product_id")
    if not product_id:
        await state.clear()
        await message.answer("Phiên nhập số lượng đã hết hạn. Vui lòng chọn lại sản phẩm.")
        return

    async with async_session() as session:
        product = await product_service.get_product(session, int(product_id))
        if not product or not product.is_active:
            await state.clear()
            await message.answer("Sản phẩm không tồn tại hoặc đã ngừng bán.")
            return
        stock = await product_service.get_stock_count(session, int(product_id))
        if stock <= 0:
            await state.clear()
            await message.answer("Sản phẩm đã hết hàng.")
            return

        minimum = max(1, int(product.min_quantity or 1))
        maximum = min(stock, max(int(product.max_quantity or 1), minimum))

    if requested_quantity < minimum or requested_quantity > maximum:
        await message.answer(
            f"Số lượng không hợp lệ. Vui lòng nhập từ <b>{minimum}</b> đến <b>{maximum}</b>."
        )
        return

    await state.clear()
    price = wallet_service.money(product.price)
    total_price = wallet_service.money(price * requested_quantity)
    await message.answer(
        "🧾 <b>Xác nhận mua hàng</b>\n\n"
        f"Sản phẩm: <b>{product.name}</b>\n"
        f"Đơn giá: <b>{wallet_service.format_vnd(price)}</b>\n"
        f"Số lượng: <b>{requested_quantity}</b>\n"
        f"Tổng tiền: <b>{wallet_service.format_vnd(total_price)}</b>\n"
        f"Tồn kho hiện tại: <b>{stock}</b>\n\n"
        "Nếu đồng ý, bấm xác nhận mua để hệ thống trừ ví và giao hàng tự động.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Xác nhận mua", callback_data=f"purchase_{product.id}_{requested_quantity}")],
            [InlineKeyboardButton(text="Nhập lại số lượng", callback_data=f"qtyinput_{product.id}")],
            [InlineKeyboardButton(text="Hủy", callback_data=f"prod_{product.id}")],
        ]),
    )


@router.callback_query(F.data.startswith("purchase_"))
async def purchase_product(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    _, product_id_raw, quantity_raw = callback.data.split("_")
    product_id = int(product_id_raw)
    requested_quantity = max(1, int(quantity_raw))
    await state.clear()

    async with async_session() as session:
        user = await session.get(User, user_id)
        if not user or user.is_banned:
            await callback.answer("Tài khoản không hợp lệ hoặc đã bị cấm.", show_alert=True)
            return

        product = await product_service.get_product(session, product_id)
        if not product or not product.is_active:
            await callback.answer("Sản phẩm không tồn tại hoặc đã ngừng bán.", show_alert=True)
            return

        stock = await product_service.get_stock_count(session, product_id)
        quantity = _clamp_quantity(product, stock, requested_quantity)
        price = wallet_service.money(product.price)
        total_price = wallet_service.money(price * quantity)
        balance = wallet_service.money(user.wallet_balance)
        product_name = product.name
        has_enough = balance >= total_price

    if not has_enough:
        shortage = total_price - balance
        await callback.message.edit_text(
            f"❌ <b>Số dư ví không đủ</b>\n\n"
            f"Sản phẩm: {product_name}\n"
            f"Số lượng: <b>{quantity}</b>\n"
            f"Tổng tiền: <b>{wallet_service.format_vnd(total_price)}</b>\n"
            f"Số dư hiện tại: <b>{wallet_service.format_vnd(balance)}</b>\n"
            f"Cần thêm: <b>{wallet_service.format_vnd(shortage)}</b>\n\n"
            "Vui lòng nạp tiền vào ví rồi thử lại.",
            reply_markup=_fail_keyboard(),
        )
        await callback.answer()
        return

    await callback.answer("Đang xử lý thanh toán...")

    async with async_session() as session:
        result = await wallet_service.pay_product_with_wallet(
            session=session,
            bot=callback.bot,
            user_id=user_id,
            product_id=product_id,
            quantity=quantity,
        )

    if not result.success:
        await callback.message.edit_text(
            f"❌ {result.message}",
            reply_markup=_fail_keyboard(),
        )
        return

    order_id = result.order.id if result.order else None
    text = (
        "✅ <b>Mua hàng thành công!</b>\n\n"
        f"Mã đơn hàng: <b>#{order_id}</b>\n"
        f"Sản phẩm: <b>{product_name}</b>\n"
        f"Số lượng: <b>{quantity}</b>\n"
        f"Số tiền: <b>{wallet_service.format_vnd(total_price)}</b>\n"
        "Thông tin sản phẩm đã được bot gửi ở tin nhắn giao hàng.\n\n"
        "Cảm ơn bạn đã mua sắm tại shop!"
    )
    await callback.message.edit_text(text, reply_markup=_success_keyboard())
