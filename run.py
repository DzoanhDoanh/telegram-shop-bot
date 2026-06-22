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
from app.handlers.admin import dashboard, inventory, orders as admin_orders, products, stats, users
from app.handlers.user import catalog, checkout, orders as user_orders, start, wallet
from app.web.main import app as web_app, set_bot

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


async def run_bot() -> None:
    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    storage = RedisStorage.from_url(settings.REDIS_URL)
    dp = Dispatcher(storage=storage)

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

    set_bot(bot)
    logging.info("🤖 Bot started")

    try:
        await set_bot_commands(bot)
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


async def run_web() -> None:
    config = uvicorn.Config(
        app=web_app,
        host=settings.WEB_HOST,
        port=settings.WEB_PORT,
        log_level="warning",
    )
    server = uvicorn.Server(config)
    logging.info("🌐 Starting web admin at http://%s:%s", settings.WEB_HOST, settings.WEB_PORT)
    try:
        await server.serve()
    except SystemExit as exc:
        logging.error(
            "Web admin failed to start on %s:%s (likely port already in use). Bot will keep running. exit_code=%s",
            settings.WEB_HOST,
            settings.WEB_PORT,
            exc.code,
        )
    except OSError:
        logging.exception(
            "Web admin failed to bind on %s:%s. Bot will keep running.",
            settings.WEB_HOST,
            settings.WEB_PORT,
        )


async def main() -> None:
    bot_task = asyncio.create_task(run_bot(), name="bot")
    web_task = asyncio.create_task(run_web(), name="web")

    done, pending = await asyncio.wait({bot_task, web_task}, return_when=asyncio.FIRST_EXCEPTION)

    if bot_task in done and (bot_exc := bot_task.exception()) is not None:
        web_task.cancel()
        await asyncio.gather(web_task, return_exceptions=True)
        raise bot_exc

    await asyncio.gather(*pending, return_exceptions=False)


if __name__ == "__main__":
    asyncio.run(main())
