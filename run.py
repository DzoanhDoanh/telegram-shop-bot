"""
Run both the Telegram bot and Web Admin Panel concurrently.
Usage: python run.py
"""
import asyncio
import logging
import uvicorn
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import BotCommand

from app.config import settings
from app.web.main import app as web_app, set_bot
from app.handlers.user import start, catalog, checkout, orders as user_orders, wallet
from app.handlers.admin import orders as admin_orders, dashboard, stats, products, inventory, users

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


async def set_bot_commands(bot: Bot) -> None:
    await bot.set_my_commands([
        BotCommand(command="start", description="Mở menu chính"),
        BotCommand(command="shop", description="Xem sản phẩm"),
        BotCommand(command="search", description="Tìm kiếm sản phẩm"),
        BotCommand(command="orders", description="Đơn hàng của tôi"),
        BotCommand(command="wallet", description="Ví của tôi"),
        BotCommand(command="support", description="Liên hệ hỗ trợ"),
        BotCommand(command="help", description="Hướng dẫn mua hàng"),
    ])


async def run_bot():
    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    storage = RedisStorage.from_url(settings.REDIS_URL)
    dp = Dispatcher(storage=storage)

    # Register all routers
    dp.include_router(start.router)
    dp.include_router(wallet.router)
    dp.include_router(catalog.router)
    dp.include_router(checkout.router)
    dp.include_router(user_orders.router)
    dp.include_router(admin_orders.router)
    dp.include_router(dashboard.router)
    dp.include_router(stats.router)
    dp.include_router(products.router)
    dp.include_router(inventory.router)
    dp.include_router(users.router)

    # Share bot instance with web admin for approve/reject delivery
    set_bot(bot)

    logging.info("🤖 Bot started")
    await set_bot_commands(bot)
    await dp.start_polling(bot)

async def run_web():
    config = uvicorn.Config(
        app=web_app,
        host=settings.WEB_HOST,
        port=settings.WEB_PORT,
        log_level="warning",
    )
    server = uvicorn.Server(config)
    logging.info("🌐 Web admin started at http://%s:%s", settings.WEB_HOST, settings.WEB_PORT)
    await server.serve()

async def main():
    await asyncio.gather(
        run_bot(),
        run_web(),
    )

if __name__ == "__main__":
    asyncio.run(main())
