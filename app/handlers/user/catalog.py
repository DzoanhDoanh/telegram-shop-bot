import html

from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.config import settings
from app.database.models import User
from app.database.session import async_session
from app.keyboards.user_kb import BTN_SEARCH, get_persistent_menu_kb
from app.services import app_config_service, product_service

router = Router()


class SearchState(StatesGroup):
    waiting_for_query = State()


CATALOG_TEXT = (
    "🛍 <b>Chọn danh mục sản phẩm</b>\n\n"
    "Khám phá các sản phẩm số đang có sẵn. Chọn danh mục phù hợp để xem giá, tồn kho và đặt mua nhanh."
)


async def _catalog_app_config():
    async with async_session() as session:
        return await app_config_service.get_app_config_view(session)


def _support_url(support_username: str = "") -> str | None:
    support_username = (support_username or "").strip().lstrip("@")
    if not support_username:
        return None
    return f"https://t.me/{support_username}"


async def _ensure_callback_user_allowed(callback: types.CallbackQuery) -> bool:
    async with async_session() as session:
        user = await session.get(User, callback.from_user.id)
        app_config = await app_config_service.get_app_config_view(session)
        if user and user.is_banned:
            await callback.message.answer(
                "🚫 Tài khoản của bạn đã bị cấm sử dụng bot.",
                reply_markup=get_persistent_menu_kb(app_config.show_terms_button, app_config.show_help_button),
            )
            await callback.answer()
            return False
        if app_config.maintenance_mode and callback.from_user.id not in settings.ADMIN_IDS:
            await callback.message.answer(
                f"{app_config.shop_display_name} đang tạm bảo trì. Vui lòng quay lại sau.",
                reply_markup=get_persistent_menu_kb(app_config.show_terms_button, app_config.show_help_button),
            )
            await callback.answer()
            return False
    return True


def _build_category_keyboard(categories) -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    keyboard.inline_keyboard.append([
        InlineKeyboardButton(text="🔎 Tìm kiếm sản phẩm", callback_data="product_search")
    ])
    for category in categories:
        text = f"{category.emoji} {category.name}" if category.emoji else category.name
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(text=text, callback_data=f"cat_{category.id}")
        ])
    return keyboard


def _build_support_button(support_username: str = "") -> InlineKeyboardButton | None:
    support_url = _support_url(support_username)
    if not support_url:
        return None
    return InlineKeyboardButton(text="💬 Hỗ trợ", url=support_url)


def _product_button_text(product, stock: int | None = None) -> str:
    text = f"{product.name} - {product.price:,.0f}đ"
    if getattr(product, "delivery_mode", "inventory") == "fixed_content":
        text += " | Giao tự động"
    elif stock is not None:
        text += f" | Còn {stock}"
    return text


def _product_detail_text(product, stock: int) -> str:
    safe_name = html.escape(product.name or "Sản phẩm")
    safe_description = html.escape(product.description or "")
    is_fixed_content = getattr(product, "delivery_mode", "inventory") == "fixed_content"
    stock_status = (
        f"✅ Còn sẵn: <b>{stock}</b> đơn vị có thể giao ngay"
        if stock > 0
        else "⛔ Tạm hết hàng, vui lòng quay lại sau hoặc liên hệ hỗ trợ"
    )

    if is_fixed_content:
        quantity_note = "1"
        delivery_note = "📩 Sau khi thanh toán, bot sẽ gửi ngay thông tin sản phẩm cho bạn"
    elif getattr(product, "allow_quantity_selection", False):
        min_quantity = int(product.min_quantity or 1)
        max_quantity = min(stock, max(int(product.max_quantity or 1), min_quantity))
        quantity_note = f"Được chọn từ {min_quantity} đến {max_quantity}"
        delivery_note = "📩 Sau khi thanh toán, bot sẽ giao đúng số lượng bạn đã chọn"
    else:
        quantity_note = "1"
        delivery_note = "📩 Sau khi thanh toán, bot sẽ giao thông tin sản phẩm cho bạn"

    text = f"📦 <b>{safe_name}</b>\n\n"
    if safe_description:
        text += f"📝 Mô tả: {safe_description}\n\n"
    text += f"💰 Đơn giá: <b>{product.price:,.0f}đ</b>\n"
    text += f"🔢 Số lượng mua: <b>{html.escape(quantity_note)}</b>\n"
    if not is_fixed_content:
        text += f"📊 {stock_status}\n"
    text += f"{delivery_note}\n"
    return text


def _build_product_detail_keyboard(product, stock: int, support_username: str = "") -> InlineKeyboardMarkup:
    buttons = []
    can_buy = stock > 0 or getattr(product, "delivery_mode", "inventory") == "fixed_content"
    if can_buy:
        buttons.append([InlineKeyboardButton(text="🛒 Mua ngay", callback_data=f"buy_{product.id}")])
        if getattr(product, "delivery_mode", "inventory") != "fixed_content" and getattr(product, "allow_quantity_selection", False):
            buttons.append([InlineKeyboardButton(text="⌨️ Nhập số lượng", callback_data=f"qtyinput_{product.id}")])

    buttons.append([InlineKeyboardButton(text="🔄 Làm mới", callback_data=f"refresh_prod_{product.id}")])

    support_button = _build_support_button(support_username)
    if support_button:
        buttons.append([support_button])

    buttons.append([InlineKeyboardButton(text="🔙 Quay lại", callback_data=f"cat_{product.category_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def _get_categories():
    async with async_session() as session:
        return await product_service.get_categories(session)


def _build_search_results_keyboard(products, stock_counts: dict[int, int] | None = None) -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    stock_counts = stock_counts or {}
    for product in products:
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(
                text=_product_button_text(product, stock_counts.get(product.id)),
                callback_data=f"prod_{product.id}",
            )
        ])
    keyboard.inline_keyboard.append([
        InlineKeyboardButton(text="🔎 Tìm lại", callback_data="product_search"),
        InlineKeyboardButton(text="🔙 Danh mục", callback_data="shop_catalog"),
    ])
    return keyboard


async def _send_search_prompt(message: types.Message, state: FSMContext) -> None:
    app_config = await _catalog_app_config()
    if app_config.maintenance_mode and message.from_user.id not in settings.ADMIN_IDS:
        await message.answer(
            f"{app_config.shop_display_name} đang tạm bảo trì. Vui lòng quay lại sau.",
            reply_markup=get_persistent_menu_kb(app_config.show_terms_button, app_config.show_help_button),
        )
        return
    await state.set_state(SearchState.waiting_for_query)
    await message.answer(
        "🔎 <b>Tìm kiếm sản phẩm</b>\n\n"
        "Nhập tên hoặc từ khóa sản phẩm bạn muốn tìm.\n"
        "Ví dụ: <code>netflix</code>, <code>game</code>, <code>drive</code>",
        reply_markup=get_persistent_menu_kb(app_config.show_terms_button, app_config.show_help_button),
    )


async def send_catalog(message: types.Message) -> None:
    categories = await _get_categories()
    app_config = await _catalog_app_config()

    if app_config.maintenance_mode and message.from_user.id not in settings.ADMIN_IDS:
        await message.answer(
            f"{app_config.shop_display_name} đang tạm bảo trì. Vui lòng quay lại sau hoặc nhắn hỗ trợ nếu bạn cần kiểm tra đơn đang dở.",
            reply_markup=get_persistent_menu_kb(app_config.show_terms_button, app_config.show_help_button),
        )
        return

    if not categories:
        await message.answer(
            "🛍 Shop đang cập nhật danh mục sản phẩm. Vui lòng quay lại sau hoặc bấm 💬 Hỗ trợ để được tư vấn nhanh.",
            reply_markup=get_persistent_menu_kb(app_config.show_terms_button, app_config.show_help_button),
        )
        return

    await message.answer(CATALOG_TEXT, reply_markup=_build_category_keyboard(categories))


@router.message(Command("search"))
@router.message(F.text == BTN_SEARCH)
async def cmd_search(message: types.Message, state: FSMContext):
    await _send_search_prompt(message, state)


@router.callback_query(F.data == "product_search")
async def product_search(callback: types.CallbackQuery, state: FSMContext):
    app_config = await _catalog_app_config()
    if app_config.maintenance_mode and callback.from_user.id not in settings.ADMIN_IDS:
        await callback.message.answer(
            f"{app_config.shop_display_name} đang tạm bảo trì. Vui lòng quay lại sau.",
            reply_markup=get_persistent_menu_kb(app_config.show_terms_button, app_config.show_help_button),
        )
        await callback.answer()
        return
    await state.set_state(SearchState.waiting_for_query)
    await callback.message.answer(
        "🔎 <b>Tìm kiếm sản phẩm</b>\n\n"
        "Nhập tên hoặc từ khóa sản phẩm bạn muốn tìm.",
        reply_markup=get_persistent_menu_kb(app_config.show_terms_button, app_config.show_help_button),
    )
    await callback.answer()


@router.message(SearchState.waiting_for_query)
async def process_product_search(message: types.Message, state: FSMContext):
    app_config = await _catalog_app_config()
    if app_config.maintenance_mode and message.from_user.id not in settings.ADMIN_IDS:
        await state.clear()
        await message.answer(
            f"{app_config.shop_display_name} đang tạm bảo trì. Vui lòng quay lại sau.",
            reply_markup=get_persistent_menu_kb(app_config.show_terms_button, app_config.show_help_button),
        )
        return
    query = (message.text or "").strip()
    if len(query) < 2:
        await message.answer("Vui lòng nhập ít nhất 2 ký tự để tìm kiếm.")
        return

    async with async_session() as session:
        products = await product_service.search_products(session, query)
        stock_counts = await product_service.get_stock_counts(session, [product.id for product in products])

    await state.clear()
    if not products:
        await message.answer(
            f"Không tìm thấy sản phẩm nào với từ khóa <b>{html.escape(query)}</b>.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔎 Tìm lại", callback_data="product_search")],
                [InlineKeyboardButton(text="🔙 Danh mục", callback_data="shop_catalog")],
            ]),
        )
        return

    await message.answer(
        f"🔎 <b>Kết quả tìm kiếm</b> cho: <code>{html.escape(query)}</code>\n\n"
        "Chọn sản phẩm để xem chi tiết và mua hàng.",
        reply_markup=_build_search_results_keyboard(products, stock_counts),
    )


@router.callback_query(F.data == "shop_catalog")
async def show_categories(callback: types.CallbackQuery):
    if not await _ensure_callback_user_allowed(callback):
        return
    app_config = await _catalog_app_config()
    if app_config.maintenance_mode and callback.from_user.id not in settings.ADMIN_IDS:
        await callback.message.answer(
            f"{app_config.shop_display_name} đang tạm bảo trì. Vui lòng quay lại sau hoặc nhắn hỗ trợ nếu bạn cần kiểm tra đơn đang dở.",
            reply_markup=get_persistent_menu_kb(app_config.show_terms_button, app_config.show_help_button),
        )
        await callback.answer()
        return

    categories = await _get_categories()

    if not categories:
        await callback.message.answer(
            "🛍 Shop đang cập nhật danh mục sản phẩm. Vui lòng quay lại sau hoặc bấm 💬 Hỗ trợ để được tư vấn nhanh.",
            reply_markup=get_persistent_menu_kb(app_config.show_terms_button, app_config.show_help_button),
        )
        await callback.answer()
        return

    await callback.message.edit_text(
        CATALOG_TEXT,
        reply_markup=_build_category_keyboard(categories),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("cat_"))
async def show_products(callback: types.CallbackQuery):
    if not await _ensure_callback_user_allowed(callback):
        return
    cat_id = int(callback.data.split("_")[1])
    async with async_session() as session:
        products = await product_service.get_products_by_category(session, cat_id)
        stock_counts = await product_service.get_stock_counts(session, [product.id for product in products])

    app_config = await _catalog_app_config()
    if not products:
        await callback.message.answer(
            "Danh mục này tạm thời chưa có sản phẩm. Shop sẽ bổ sung sớm, bạn có thể chọn danh mục khác hoặc liên hệ hỗ trợ.",
            reply_markup=get_persistent_menu_kb(app_config.show_terms_button, app_config.show_help_button),
        )
        await callback.answer()
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    for product in products:
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(
                text=_product_button_text(product, stock_counts.get(product.id)),
                callback_data=f"prod_{product.id}",
            )
        ])

    keyboard.inline_keyboard.append([InlineKeyboardButton(text="🔙 Quay lại", callback_data="shop_catalog")])

    await callback.message.edit_text(
        "🛍 <b>Sản phẩm đang bán</b>\n\nChọn sản phẩm để xem mô tả, tồn kho và đặt mua ngay.",
        reply_markup=keyboard,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("prod_"))
async def show_product_detail(callback: types.CallbackQuery):
    if not await _ensure_callback_user_allowed(callback):
        return
    prod_id = int(callback.data.split("_")[1])
    async with async_session() as session:
        product = await product_service.get_product(session, prod_id)
        stock = await product_service.get_stock_count(session, prod_id)

    app_config = await _catalog_app_config()
    if not product or not product.is_active:
        await callback.message.answer(
            "Sản phẩm này hiện không còn khả dụng. Vui lòng chọn sản phẩm khác hoặc liên hệ hỗ trợ nếu cần tư vấn.",
            reply_markup=get_persistent_menu_kb(app_config.show_terms_button, app_config.show_help_button),
        )
        await callback.answer()
        return

    await callback.message.edit_text(
        _product_detail_text(product, stock),
        reply_markup=_build_product_detail_keyboard(product, stock, app_config.support_username),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("refresh_prod_"))
async def refresh_product_detail(callback: types.CallbackQuery):
    if not await _ensure_callback_user_allowed(callback):
        return
    prod_id = int(callback.data.removeprefix("refresh_prod_"))
    async with async_session() as session:
        product = await product_service.get_product(session, prod_id)
        stock = await product_service.get_stock_count(session, prod_id)

    app_config = await _catalog_app_config()
    if not product or not product.is_active:
        await callback.message.edit_text(
            "Sản phẩm này hiện không còn khả dụng. Có thể shop đã ẩn, đổi tên hoặc ngừng bán sản phẩm này.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Danh mục", callback_data="shop_catalog")]
            ]),
        )
        await callback.answer("Sản phẩm đã được cập nhật", show_alert=False)
        return

    await callback.message.edit_text(
        _product_detail_text(product, stock),
        reply_markup=_build_product_detail_keyboard(product, stock, app_config.support_username),
    )
    await callback.answer("Đã làm mới sản phẩm")
