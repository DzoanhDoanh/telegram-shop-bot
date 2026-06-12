import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage

from app.config import settings
from app.handlers.user import start, catalog, checkout, orders as user_orders, wallet
from app.handlers.admin import orders as admin_orders, dashboard, stats, users

logging.basicConfig(level=logging.INFO)

async def main():
    if not settings.BOT_TOKEN:
        logging.error("BOT_TOKEN is not set in environment variables.")
        return

    # Setup Redis Storage for FSM
    storage = RedisStorage.from_url(settings.REDIS_URL)
    
    bot = Bot(
        token=settings.BOT_TOKEN, 
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = Dispatcher(storage=storage)

    # Register routers
    dp.include_router(start.router)
    dp.include_router(wallet.router)
    dp.include_router(catalog.router)
    dp.include_router(checkout.router)
    dp.include_router(user_orders.router)
    dp.include_router(admin_orders.router)
    dp.include_router(dashboard.router)
    dp.include_router(stats.router)
    dp.include_router(users.router)

    logging.info("Starting bot...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
