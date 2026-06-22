from aiogram import F, Router, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.config import settings
from app.database.models import User
from app.database.session import async_session
from app.keyboards.user_kb import get_persistent_menu_kb
from app.services import app_config_service, order_service, payment_policy_service, product_service, voucher_service, wallet_service

router = Router()


async def _checkout_app_config():
    async with async_session() as session:
        return await app_config_service.get_app_config_view(session)


class QuantityInputState(StatesGroup):
    waiting_for_quantity = State()


class VoucherInputState(StatesGroup):
    waiting_for_code = State()


def _fail_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Nạp tiền vào ví", callback_data="wallet_deposit")],
        [InlineKeyboardButton(text="Xem sản phẩm khác", callback_data="shop_catalog")],
    ])


def _success_keyboard(order_id: int | None = None) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="Mua thêm", callback_data="shop_catalog")],
        [InlineKeyboardButton(text="Xem ví", callback_data="wallet_home")],
        [InlineKeyboardButton(text="Xem đơn hàng", callback_data="shop_orders")],
    ]
    if order_id:
        rows.append([InlineKeyboardButton(text="Hỗ trợ về đơn này", callback_data=f"order_support_{order_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _clamp_quantity(product, stock: int, requested_quantity: int) -> int:
    if getattr(product, "delivery_mode", "inventory") == "fixed_content":
        return 1
    if not getattr(product, "allow_quantity_selection", False):
        return 1
    minimum = max(1, int(getattr(product, "min_quantity", 1) or 1))
    maximum = max(minimum, int(getattr(product, "max_quantity", minimum) or minimum))
    return max(minimum, min(requested_quantity, maximum, max(stock, 1)))


def _payment_action_keyboard(product, stock: int, quantity: int, voucher_code: str | None = None) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []
    if getattr(product, "delivery_mode", "inventory") != "fixed_content" and stock > 0 and getattr(product, "allow_quantity_selection", False):
        row: list[InlineKeyboardButton] = []
        if quantity > max(1, int(product.min_quantity or 1)):
            row.append(InlineKeyboardButton(text="➖ Giảm", callback_data=f"qty_{product.id}_{quantity - 1}"))
        if quantity < min(stock, max(int(product.max_quantity or 1), int(product.min_quantity or 1))):
            row.append(InlineKeyboardButton(text="➕ Tăng", callback_data=f"qty_{product.id}_{quantity + 1}"))
        if row:
            buttons.append(row)
        buttons.append([InlineKeyboardButton(text="⌨️ Nhập số lượng", callback_data=f"qtyinput_{product.id}")])
    buttons.append([InlineKeyboardButton(text="🎟️ Nhập mã giảm giá", callback_data=f"voucherinput_{product.id}_{quantity}")])

    policy = payment_policy_service.get_policy_view(product)
    if policy.allowed_methods == (payment_policy_service.PAYMENT_METHOD_WALLET,):
        buttons.append([InlineKeyboardButton(text="Thanh toán bằng ví", callback_data=f"purchase_wallet_{product.id}_{quantity}_{voucher_code or 'none'}")])
    elif policy.allowed_methods == (payment_policy_service.PAYMENT_METHOD_DIRECT_BANK,):
        buttons.append([InlineKeyboardButton(text="Chuyển khoản trực tiếp", callback_data=f"purchase_direct_bank_{product.id}_{quantity}_{voucher_code or 'none'}")])
    else:
        buttons.append([
            InlineKeyboardButton(text="Thanh toán bằng ví", callback_data=f"purchase_wallet_{product.id}_{quantity}_{voucher_code or 'none'}"),
            InlineKeyboardButton(text="Chuyển khoản trực tiếp", callback_data=f"purchase_direct_bank_{product.id}_{quantity}_{voucher_code or 'none'}"),
        ])
    buttons.append([InlineKeyboardButton(text="Hủy", callback_data=f"prod_{product.id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _build_payment_note_text(product, balance, policy: payment_policy_service.PaymentPolicyView) -> str:
    balance_line = f"Số dư hiện tại: <b>{wallet_service.format_vnd(balance)}</b>\n"
    return balance_line + f"Hình thức thanh toán: <b>{policy.mode_label}</b>\n\n{policy.checkout_hint}"


async def _render_confirmation(callback: types.CallbackQuery, product_id: int, requested_quantity: int | None = None, voucher_code: str | None = None):
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
        if product.delivery_mode != "fixed_content" and stock <= 0:
            await callback.answer("Sản phẩm đã hết hàng.", show_alert=True)
            return

        default_quantity = int(product.min_quantity or 1) if product.allow_quantity_selection and product.delivery_mode != "fixed_content" else 1
        quantity = _clamp_quantity(product, stock, requested_quantity or default_quantity)
        price = wallet_service.money(product.price)
        original_total = wallet_service.money(price * quantity)
        discount_amount = wallet_service.money(0)
        total_price = original_total
        applied_voucher = None
        clean_voucher_code = (voucher_code or "").strip()
        if clean_voucher_code:
            voucher_validation = await voucher_service.validate_voucher(
                session=session,
                code=clean_voucher_code,
                user_id=user_id,
                product=product,
                quantity=quantity,
                order_amount=original_total,
            )
            if voucher_validation.ok and voucher_validation.voucher:
                applied_voucher = voucher_validation.voucher
                discount_amount = wallet_service.money(voucher_validation.discount_amount)
                total_price = wallet_service.money(voucher_validation.final_amount)
            else:
                clean_voucher_code = ""
        balance = wallet_service.money(user.wallet_balance)
        payment_policy = payment_policy_service.get_policy_view(product)

    if product.delivery_mode == "fixed_content":
        quantity_note = "Sản phẩm này giao nội dung cố định nên mỗi lần mua chỉ nhận 1 nội dung."
        delivery_note = "Sau khi thanh toán, bot sẽ gửi ngay nội dung/link của sản phẩm trong một tin nhắn riêng."
    else:
        quantity_note = "Sản phẩm này bán cố định 1 đơn vị mỗi lần mua." if not product.allow_quantity_selection else (
            f"Bạn có thể chọn từ <b>{int(product.min_quantity or 1)}</b> đến <b>{min(stock, max(int(product.max_quantity or 1), int(product.min_quantity or 1)))}</b> đơn vị, hoặc bấm nút nhập số lượng để gõ trực tiếp."
        )
        delivery_note = "Sau khi thanh toán, bot sẽ giao đúng số lượng bạn đã chọn."

    stock_line = ""
    if product.delivery_mode != "fixed_content":
        stock_line = f"Tồn kho hiện tại: <b>{stock}</b>\n"

    voucher_lines = ""
    if applied_voucher and discount_amount > 0:
        voucher_lines = (
            f"Mã giảm giá: <b>{applied_voucher.code}</b>\n"
            f"Giá gốc: <b>{wallet_service.format_vnd(original_total)}</b>\n"
            f"Giảm giá: <b>{wallet_service.format_vnd(discount_amount)}</b>\n"
        )

    await callback.message.edit_text(
        "🧾 <b>Xác nhận mua hàng</b>\n\n"
        f"Sản phẩm: <b>{product.name}</b>\n"
        f"Đơn giá: <b>{wallet_service.format_vnd(price)}</b>\n"
        f"Số lượng: <b>{quantity}</b>\n"
        f"{voucher_lines}"
        f"Tổng thanh toán: <b>{wallet_service.format_vnd(total_price)}</b>\n"
        f"{stock_line}"
        f"{_build_payment_note_text(product, balance, payment_policy)}\n\n"
        f"{quantity_note}\n"
        f"{delivery_note}\n\n"
        "Chọn cách thanh toán phù hợp ở các nút bên dưới.",
        reply_markup=_payment_action_keyboard(product, stock, quantity, applied_voucher.code if applied_voucher else None),
    )


@router.callback_query(F.data.startswith("buy_"))
async def confirm_purchase(callback: types.CallbackQuery, state: FSMContext):
    app_config = await _checkout_app_config()
    if app_config.maintenance_mode and callback.from_user.id not in settings.ADMIN_IDS:
        await callback.message.answer(
            f"{app_config.shop_display_name} đang tạm bảo trì. Vui lòng quay lại sau để tiếp tục mua hàng.",
            reply_markup=get_persistent_menu_kb(app_config.show_terms_button, app_config.show_help_button),
        )
        await callback.answer()
        return
    product_id = int(callback.data.split("_")[1])
    await state.clear()
    await _render_confirmation(callback, product_id)
    await callback.answer()


@router.callback_query(F.data.startswith("qty_"))
async def update_purchase_quantity(callback: types.CallbackQuery):
    _, product_id, quantity = callback.data.split("_")
    await _render_confirmation(callback, int(product_id), int(quantity))
    await callback.answer()


@router.callback_query(F.data.startswith("voucherinput_"))
async def request_voucher_input(callback: types.CallbackQuery, state: FSMContext):
    _, product_id, quantity = callback.data.split("_")
    await state.set_state(VoucherInputState.waiting_for_code)
    await state.update_data(product_id=int(product_id), quantity=int(quantity))
    await callback.message.answer(
        "🎟️ <b>Nhập mã giảm giá</b>\n\nGửi mã voucher của bạn, ví dụ: <code>SALE10</code>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Bỏ qua voucher", callback_data=f"buy_{product_id}")],
        ]),
    )
    await callback.answer()


@router.message(VoucherInputState.waiting_for_code)
async def handle_voucher_input(message: types.Message, state: FSMContext):
    code = (message.text or "").strip()
    data = await state.get_data()
    product_id = data.get("product_id")
    quantity = data.get("quantity") or 1
    await state.clear()
    if not product_id:
        await message.answer("Phiên nhập mã đã hết hạn. Vui lòng chọn lại sản phẩm.")
        return

    async with async_session() as session:
        user = await session.get(User, message.from_user.id)
        product = await product_service.get_product(session, int(product_id))
        stock = await product_service.get_stock_count(session, int(product_id))
        if not user or not product or not product.is_active:
            await message.answer("Không thể áp dụng voucher cho sản phẩm này ngay lúc này.")
            return
        actual_quantity = _clamp_quantity(product, stock, int(quantity))
        price = wallet_service.money(product.price)
        original_total = wallet_service.money(price * actual_quantity)
        voucher_validation = await voucher_service.validate_voucher(
            session=session,
            code=code,
            user_id=message.from_user.id,
            product=product,
            quantity=actual_quantity,
            order_amount=original_total,
        )
        if not voucher_validation.ok or not voucher_validation.voucher:
            await message.answer(f"❌ {voucher_validation.message}")
            return
        discount_amount = wallet_service.money(voucher_validation.discount_amount)
        total_price = wallet_service.money(voucher_validation.final_amount)
        balance = wallet_service.money(user.wallet_balance)
        payment_policy = payment_policy_service.get_policy_view(product)

    delivery_note = (
        "Sau khi thanh toán, bot sẽ gửi ngay nội dung/link của sản phẩm trong một tin nhắn riêng."
        if product.delivery_mode == "fixed_content"
        else "Sau khi thanh toán, bot sẽ giao đúng số lượng bạn đã chọn."
    )

    await message.answer(
        "🧾 <b>Xác nhận mua hàng</b>\n\n"
        f"Sản phẩm: <b>{product.name}</b>\n"
        f"Đơn giá: <b>{wallet_service.format_vnd(price)}</b>\n"
        f"Số lượng: <b>{actual_quantity}</b>\n"
        f"Mã giảm giá: <b>{voucher_validation.voucher.code}</b>\n"
        f"Giá gốc: <b>{wallet_service.format_vnd(original_total)}</b>\n"
        f"Giảm giá: <b>{wallet_service.format_vnd(discount_amount)}</b>\n"
        f"Tổng thanh toán: <b>{wallet_service.format_vnd(total_price)}</b>\n"
        f"{_build_payment_note_text(product, balance, payment_policy)}\n\n"
        f"{delivery_note}\n\n"
        "Chọn cách thanh toán phù hợp ở các nút bên dưới.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=(
            _payment_action_keyboard(product, stock, actual_quantity, voucher_validation.voucher.code).inline_keyboard
            + [[InlineKeyboardButton(text="Nhập lại mã khác", callback_data=f"voucherinput_{product.id}_{actual_quantity}")]]
        )),
    )


@router.callback_query(F.data.startswith("qtyinput_"))
async def request_quantity_input(callback: types.CallbackQuery, state: FSMContext):
    app_config = await _checkout_app_config()
    if app_config.maintenance_mode and callback.from_user.id not in settings.ADMIN_IDS:
        await callback.message.answer(
            f"{app_config.shop_display_name} đang tạm bảo trì. Vui lòng quay lại sau để tiếp tục mua hàng.",
            reply_markup=get_persistent_menu_kb(app_config.show_terms_button, app_config.show_help_button),
        )
        await callback.answer()
        return
    product_id = int(callback.data.split("_")[1])

    async with async_session() as session:
        product = await product_service.get_product(session, product_id)
        if not product or not product.is_active:
            await callback.answer("Sản phẩm không tồn tại hoặc đã ngừng bán.", show_alert=True)
            return
        if product.delivery_mode == "fixed_content":
            await callback.answer("Sản phẩm này dùng nội dung có sẵn nên không cần nhập số lượng.", show_alert=True)
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
    app_config = await _checkout_app_config()
    if not raw_text.isdigit():
        await message.answer(
            "Vui lòng nhập một số nguyên hợp lệ. Ví dụ: <code>2</code>.",
            reply_markup=get_persistent_menu_kb(app_config.show_terms_button, app_config.show_help_button),
        )
        return

    requested_quantity = int(raw_text)
    data = await state.get_data()
    product_id = data.get("product_id")
    if not product_id:
        await state.clear()
        await message.answer(
            "Phiên nhập số lượng đã hết hạn. Vui lòng chọn lại sản phẩm.",
            reply_markup=get_persistent_menu_kb(app_config.show_terms_button, app_config.show_help_button),
        )
        return

    async with async_session() as session:
        product = await product_service.get_product(session, int(product_id))
        if not product or not product.is_active:
            await state.clear()
            await message.answer(
                "Sản phẩm không tồn tại hoặc đã ngừng bán.",
                reply_markup=get_persistent_menu_kb(app_config.show_terms_button, app_config.show_help_button),
            )
            return
        stock = await product_service.get_stock_count(session, int(product_id))
        if stock <= 0:
            await state.clear()
            await message.answer(
                "Sản phẩm đã hết hàng.",
                reply_markup=get_persistent_menu_kb(app_config.show_terms_button, app_config.show_help_button),
            )
            return

        minimum = max(1, int(product.min_quantity or 1))
        maximum = min(stock, max(int(product.max_quantity or 1), minimum))

    if requested_quantity < minimum or requested_quantity > maximum:
        await message.answer(
            f"Số lượng không hợp lệ. Vui lòng nhập từ <b>{minimum}</b> đến <b>{maximum}</b>.",
            reply_markup=get_persistent_menu_kb(app_config.show_terms_button, app_config.show_help_button),
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
        f"Tổng thanh toán: <b>{wallet_service.format_vnd(total_price)}</b>\n"
        f"Tồn kho hiện tại: <b>{stock}</b>\n\n"
        "Sau khi thanh toán, bot sẽ giao đúng số lượng bạn đã chọn.\n\n"
        "Chọn cách thanh toán phù hợp ở các nút bên dưới.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=(
            [[InlineKeyboardButton(text="🎟️ Nhập mã giảm giá", callback_data=f"voucherinput_{product.id}_{requested_quantity}")]]
            + _payment_action_keyboard(product, stock, requested_quantity).inline_keyboard[:-1]
            + [[InlineKeyboardButton(text="Nhập lại số lượng", callback_data=f"qtyinput_{product.id}")]]
            + [[InlineKeyboardButton(text="Hủy", callback_data=f"prod_{product.id}")]]
        )),
    )


async def _load_checkout_context(user_id: int, product_id: int, requested_quantity: int, voucher_code: str | None):
    async with async_session() as session:
        user = await session.get(User, user_id)
        if not user or user.is_banned:
            return None, "Tài khoản không hợp lệ hoặc đã bị cấm."

        product = await product_service.get_product(session, product_id)
        if not product or not product.is_active:
            return None, "Sản phẩm không tồn tại hoặc đã ngừng bán."

        stock = await product_service.get_stock_count(session, product_id)
        quantity = _clamp_quantity(product, stock, requested_quantity)
        price = wallet_service.money(product.price)
        original_total = wallet_service.money(price * quantity)
        discount_amount = wallet_service.money(0)
        total_price = original_total
        applied_voucher_code = None
        if voucher_code:
            voucher_validation = await voucher_service.validate_voucher(
                session=session,
                code=voucher_code,
                user_id=user_id,
                product=product,
                quantity=quantity,
                order_amount=original_total,
            )
            if not voucher_validation.ok:
                return None, voucher_validation.message
            applied_voucher_code = voucher_validation.voucher.code if voucher_validation.voucher else None
            discount_amount = wallet_service.money(voucher_validation.discount_amount)
            total_price = wallet_service.money(voucher_validation.final_amount)
        return {
            "user": user,
            "product": product,
            "stock": stock,
            "quantity": quantity,
            "price": price,
            "original_total": original_total,
            "discount_amount": discount_amount,
            "total_price": total_price,
            "voucher_code": applied_voucher_code,
            "balance": wallet_service.money(user.wallet_balance),
            "policy": payment_policy_service.get_policy_view(product),
        }, None


async def _create_direct_bank_order(callback: types.CallbackQuery, context: dict):
    async with async_session() as session:
        order = await order_service.create_order(
            session=session,
            user_id=callback.from_user.id,
            product_id=context["product"].id,
            quantity=context["quantity"],
            total_amount=float(context["total_price"]),
            payment_method=payment_policy_service.PAYMENT_METHOD_DIRECT_BANK,
            commit=False,
            original_amount=float(context["original_total"]),
            discount_amount=float(context["discount_amount"]),
            voucher_code=context["voucher_code"],
        )
        config = await wallet_service.ensure_payment_config(session)
        order.payment_note = "Chờ khách chuyển khoản theo đúng mã đơn để hệ thống tự đối soát."
        await session.commit()
        await session.refresh(order)

    qr_url = wallet_service.build_vietqr_url(config, context["total_price"], order.order_code)
    order_code = wallet_service.get_order_code(order)
    discount_lines = ""
    if context["voucher_code"] and context["discount_amount"] > 0:
        discount_lines = (
            f"Mã giảm giá: <b>{context['voucher_code']}</b>\n"
            f"Giảm giá: <b>{wallet_service.format_vnd(context['discount_amount'])}</b>\n"
        )
    text = (
        "🏦 <b>Tạo đơn chuyển khoản thành công</b>\n\n"
        f"Mã đơn: <b>{order_code}</b>\n"
        f"Sản phẩm: <b>{context['product'].name}</b>\n"
        f"Số lượng: <b>{context['quantity']}</b>\n"
        f"{discount_lines}"
        f"Số tiền cần chuyển: <b>{wallet_service.format_vnd(context['total_price'])}</b>\n"
        f"Ngân hàng: <b>{config.bank_name or 'Chưa cấu hình'}</b>\n"
        f"Số tài khoản: <code>{config.account_no or 'Chưa cấu hình'}</code>\n"
        f"Chủ tài khoản: <b>{config.account_name or 'Chưa cấu hình'}</b>\n"
        f"Nội dung chuyển khoản: <code>{order_code}</code>\n\n"
        "Hệ thống sẽ tự xác nhận và giao hàng ngay sau khi nhận đúng tiền và đúng nội dung chuyển khoản."
    )
    rows = [[InlineKeyboardButton(text="Xem đơn hàng", callback_data="shop_orders")]]
    if qr_url:
        rows.insert(0, [InlineKeyboardButton(text="Mở QR thanh toán", url=qr_url)])
    rows.append([InlineKeyboardButton(text="Mua sản phẩm khác", callback_data="shop_catalog")])
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    if qr_url:
        try:
            await callback.message.answer_photo(
                qr_url,
                caption="📷 <b>QR chuyển khoản trực tiếp</b>\nQuét mã này để thanh toán đúng số tiền và đúng mã đơn.",
            )
        except Exception:
            await callback.message.answer(f"🔗 QR thanh toán: {qr_url}")


@router.callback_query(F.data.startswith("purchase_"))
async def purchase_product(callback: types.CallbackQuery, state: FSMContext):
    app_config = await _checkout_app_config()
    if app_config.maintenance_mode and callback.from_user.id not in settings.ADMIN_IDS:
        await callback.message.answer(
            f"{app_config.shop_display_name} đang tạm bảo trì. Vui lòng quay lại sau để tiếp tục mua hàng.",
            reply_markup=get_persistent_menu_kb(app_config.show_terms_button, app_config.show_help_button),
        )
        await callback.answer()
        return

    user_id = callback.from_user.id
    payload = callback.data.removeprefix("purchase_")
    if payload.startswith("direct_bank_"):
        payment_method = payment_policy_service.PAYMENT_METHOD_DIRECT_BANK
        rest = payload.removeprefix("direct_bank_")
    elif payload.startswith("wallet_"):
        payment_method = payment_policy_service.PAYMENT_METHOD_WALLET
        rest = payload.removeprefix("wallet_")
    else:
        await callback.message.edit_text("❌ Không nhận diện được phương thức thanh toán.", reply_markup=_fail_keyboard())
        await callback.answer()
        return

    product_id_raw, quantity_raw, voucher_code_raw = rest.split("_", 2)
    product_id = int(product_id_raw)
    requested_quantity = max(1, int(quantity_raw))
    voucher_code = None if voucher_code_raw == "none" else voucher_code_raw
    await state.clear()

    context, error_message = await _load_checkout_context(user_id, product_id, requested_quantity, voucher_code)
    if error_message:
        await callback.message.edit_text(f"❌ {error_message}", reply_markup=_fail_keyboard())
        await callback.answer()
        return

    assert context is not None
    if not payment_policy_service.is_payment_method_allowed(context["product"], payment_method):
        await callback.message.edit_text("❌ Phương thức thanh toán này không áp dụng cho sản phẩm này.", reply_markup=_fail_keyboard())
        await callback.answer()
        return

    if payment_method == payment_policy_service.PAYMENT_METHOD_WALLET:
        if context["balance"] < context["total_price"]:
            shortage = context["total_price"] - context["balance"]
            await callback.message.edit_text(
                f"❌ <b>Số dư ví không đủ</b>\n\n"
                f"Sản phẩm: {context['product'].name}\n"
                f"Số lượng: <b>{context['quantity']}</b>\n"
                f"Tổng thanh toán: <b>{wallet_service.format_vnd(context['total_price'])}</b>\n"
                f"Số dư hiện tại: <b>{wallet_service.format_vnd(context['balance'])}</b>\n"
                f"Cần thêm: <b>{wallet_service.format_vnd(shortage)}</b>\n\n"
                "Vui lòng nạp tiền vào ví rồi thử lại, hoặc chọn chuyển khoản trực tiếp nếu sản phẩm cho phép.",
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
                quantity=context["quantity"],
                voucher_code=context["voucher_code"],
            )
        if not result.success:
            await callback.message.edit_text(f"❌ {result.message}", reply_markup=_fail_keyboard())
            return

        order_code = wallet_service.get_order_code(result.order) if result.order else "N/A"
        order_id = result.order.id if result.order else None
        text = (
            "✅ <b>Mua hàng thành công!</b>\n\n"
            f"Mã đơn hàng: <b>{order_code}</b>\n"
            f"Sản phẩm: <b>{context['product'].name}</b>\n"
            f"Số lượng: <b>{context['quantity']}</b>\n"
            + (f"Mã giảm giá: <b>{context['voucher_code']}</b>\nGiảm giá: <b>{wallet_service.format_vnd(context['discount_amount'])}</b>\n" if context['voucher_code'] and context['discount_amount'] > 0 else "")
            + f"Số tiền: <b>{wallet_service.format_vnd(context['total_price'])}</b>\n"
            "Thông tin sản phẩm đã được bot gửi ở tin nhắn giao hàng.\n"
            "Nếu cần shop kiểm tra nhanh, hãy dùng nút hỗ trợ theo đúng mã đơn bên dưới.\n\n"
            "Cảm ơn bạn đã mua sắm tại shop!"
        )
        await callback.message.edit_text(text, reply_markup=_success_keyboard(order_id))
        return

    await callback.answer("Đang tạo đơn chuyển khoản...")
    await _create_direct_bank_order(callback, context)
