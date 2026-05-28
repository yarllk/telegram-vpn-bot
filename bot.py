import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeDefault

import db
import scheduler
from config import load_config
from marzban.init_client import MarzClientCache
from tgbot.handlers.user import router as user_router
from tgbot.handlers.vpn_settings import router as vpn_router
from tgbot.handlers.subscription import router as sub_router
from tgbot.middlewares.flood import ThrottlingMiddleware
from utils import broadcaster
from utils.logger import APINotificationHandler
import betterlogging as bl

logger = logging.getLogger(__name__)
config = load_config()


def setup_logging():
    bl.basic_colorized_config(level=logging.INFO)
    api_handler = APINotificationHandler(config.tg_bot.token, config.tg_bot.admin_id)
    api_handler.setLevel(logging.ERROR)
    logging.getLogger().addHandler(api_handler)


async def on_startup(bot: Bot, pool):
    await register_commands(bot)
    try:
        await broadcaster.broadcast(bot, [config.tg_bot.admin_id], "Бот запущен ✅")
    except Exception:
        pass


async def register_commands(bot: Bot):
    commands = [
        BotCommand(command="start", description="Главное меню"),
        BotCommand(command="help", description="Помощь"),
        BotCommand(command="vpn", description="Мой VPN-ключ"),
    ]
    await bot.set_my_commands(commands, scope=BotCommandScopeDefault())


async def main():
    setup_logging()

    bot = Bot(
        token=config.tg_bot.token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )

    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)

    # DB pool
    pool = await db.create_pool()
    await db.init_db(pool)

    # Marzban client cache
    marz_cache = MarzClientCache(
        base_url=config.marzban.base_url,
        config=config,
        logger=logger
    )

    # Inject pool and marz_cache into handlers via middleware data
    dp["pool"] = pool
    dp["marz_cache"] = marz_cache

    # Register routers
    dp.include_router(user_router)
    dp.include_router(vpn_router)
    dp.include_router(sub_router)

    # Throttling middleware
    dp.message.middleware(ThrottlingMiddleware())

    await on_startup(bot, pool)

    # Start background scheduler
    asyncio.create_task(scheduler.scheduler_loop(bot, pool, marz_cache))

    logger.info("Starting polling...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
