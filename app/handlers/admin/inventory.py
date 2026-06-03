from aiogram import Router, types
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.database.session import async_session
from app.database.models import Product, InventoryItem
from app.config import settings

router = Router()

class AddStockState(StatesGroup):
    waiting_for_keys = State()

@router.message(Command("stock"))
async def cmd_stock(message: types.Message):
    if message.from_user.id not in settings.ADMIN_IDS:
        return
        
    async with async_session() as session:
        products = await session.execute(select(Product))
        products = products.scalars().all()
        
        if not products:
            await message.answer("Chưa có sản phẩm nào.")
            return
            
        text = "📦 <b>TỒN KHO:</b>\n\n"
        for p in products:
            stock = await session.scalar(
                select(func.count(InventoryItem.id))
                .where(InventoryItem.product_id == p.id, InventoryItem.is_sold == False)
            )
            text += f"- {p.name} (ID: {p.id}): <b>{stock}</b> items\n"
            
        text += "\n👉 <i>Dùng lệnh /addstock [id] để thêm hàng</i>"
        await message.answer(text)

@router.message(Command("addstock"))
async def cmd_addstock(message: types.Message, state: FSMContext, command: CommandObject = None):
    if message.from_user.id not in settings.ADMIN_IDS:
        return
        
    if not command or not command.args:
        await message.answer("⚠️ Sai cú pháp! Sử dụng: <code>/addstock [product_id]</code>\nVd: <code>/addstock 1</code>")
        return
        
    try:
        product_id = int(command.args.split()[0])
    except (ValueError, IndexError):
        await message.answer("⚠️ Mã sản phẩm không hợp lệ!")
        return
        
    async with async_session() as session:
        product = await session.get(Product, product_id)
        if not product:
            await message.answer("❌ Sản phẩm không tồn tại!")
            return
            
    await state.update_data(product_id=product_id)
    await state.set_state(AddStockState.waiting_for_keys)
    
    await message.answer(
        f"📦 Đang nhập kho cho: <b>{product.name}</b>\n\n"
        f"Vui lòng gửi danh sách tài khoản/key, <b>MỖI TÀI KHOẢN/KEY TRÊN 1 DÒNG</b>.\n"
        f"(Hoặc gõ /cancel để hủy)"
    )

@router.message(AddStockState.waiting_for_keys)
async def process_keys(message: types.Message, state: FSMContext):
    if message.text == '/cancel':
        await state.clear()
        await message.answer("Đã hủy nhập kho.")
        return
        
    data = await state.get_data()
    product_id = data['product_id']
    
    keys = [k.strip() for k in message.text.split('\n') if k.strip()]
    if not keys:
        await message.answer("⚠️ Không tìm thấy key nào hợp lệ. Vui lòng gửi lại (mỗi key 1 dòng):")
        return
        
    async with async_session() as session:
        for key in keys:
            item = InventoryItem(product_id=product_id, content=key)
            session.add(item)
        await session.commit()
        
    await state.clear()
    await message.answer(f"✅ Đã thêm thành công <b>{len(keys)}</b> sản phẩm vào kho!")
