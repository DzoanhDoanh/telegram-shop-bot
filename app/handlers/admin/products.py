from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database.session import async_session
from app.database.models import Category, Product
from app.config import settings

router = Router()

class AddProductState(StatesGroup):
    waiting_for_name = State()
    waiting_for_price = State()
    waiting_for_desc = State()

@router.callback_query(F.data == "admin_products")
@router.message(Command("addproduct"))
async def start_add_product(event: types.Message | types.CallbackQuery, state: FSMContext):
    user_id = event.from_user.id
    if user_id not in settings.ADMIN_IDS:
        return

    # Create default category if missing
    async with async_session() as session:
        cat = await session.scalar(select(Category).limit(1))
        if not cat:
            cat = Category(name="General", emoji="📦")
            session.add(cat)
            await session.commit()
            await session.refresh(cat)
        await state.update_data(category_id=cat.id)

    await state.set_state(AddProductState.waiting_for_name)
    msg = "📦 <b>Thêm sản phẩm mới</b>\n\nVui lòng nhập TÊN sản phẩm (hoặc /cancel để hủy):"
    
    if isinstance(event, types.CallbackQuery):
        await event.message.edit_text(msg)
        await event.answer()
    else:
        await event.answer(msg)

@router.message(AddProductState.waiting_for_name)
async def process_name(message: types.Message, state: FSMContext):
    if message.text == '/cancel':
        await state.clear()
        await message.answer("Đã hủy thêm sản phẩm.")
        return
        
    await state.update_data(name=message.text)
    await state.set_state(AddProductState.waiting_for_price)
    await message.answer("💰 Nhập GIÁ sản phẩm (chỉ viết số, vd: 50000):")

@router.message(AddProductState.waiting_for_price)
async def process_price(message: types.Message, state: FSMContext):
    if message.text == '/cancel':
        await state.clear()
        await message.answer("Đã hủy thêm sản phẩm.")
        return
        
    try:
        price = float(message.text)
    except ValueError:
        await message.answer("⚠️ Giá không hợp lệ. Vui lòng chỉ nhập số:")
        return
        
    await state.update_data(price=price)
    await state.set_state(AddProductState.waiting_for_desc)
    await message.answer("📝 Nhập MÔ TẢ sản phẩm (hoặc gửi '-' để bỏ qua):")

@router.message(AddProductState.waiting_for_desc)
async def process_desc(message: types.Message, state: FSMContext):
    if message.text == '/cancel':
        await state.clear()
        await message.answer("Đã hủy thêm sản phẩm.")
        return
        
    desc = message.text if message.text != '-' else None
    data = await state.get_data()
    
    async with async_session() as session:
        product = Product(
            category_id=data['category_id'],
            name=data['name'],
            price=data['price'],
            description=desc
        )
        session.add(product)
        await session.commit()
        await session.refresh(product)
        
    await state.clear()
    await message.answer(
        f"✅ <b>Thêm sản phẩm thành công!</b>\n"
        f"Mã SP: {product.id}\n"
        f"Tên: {product.name}\n"
        f"Giá: {product.price:,.0f}đ\n\n"
        f"👉 Sử dụng lệnh <code>/addstock {product.id}</code> để thêm hàng (key/account) vào kho."
    )
