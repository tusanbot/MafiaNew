import asyncio
import logging
import uvicorn
from sqlalchemy import text
from aiogram import Bot, Dispatcher
from app.config import get_settings
from app.db.session import engine
from app.handlers import register_handlers
from app.health import app as health_app
from app.logging import configure_logging

async def run_bot() -> None:
    settings = get_settings()
    bot = Bot(settings.bot_token)
    dispatcher = Dispatcher()
    register_handlers(dispatcher)
    try:
        await dispatcher.start_polling(bot)
    finally:
        await bot.session.close()

async def run_http() -> None:
    settings = get_settings()
    server = uvicorn.Server(uvicorn.Config(health_app, host="0.0.0.0", port=settings.port, log_level=settings.log_level.lower()))
    await server.serve()

async def run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    logger = logging.getLogger(__name__)
    logger.info("Starting Mafia Bot")

    # Railway can briefly overlap old/new containers during a deploy. Telegram
    # allows only one long-polling consumer per bot token, so serialize polling
    # at the PostgreSQL level and let the second container wait for the first.
    async with engine.connect() as lock_connection:
        while True:
            acquired = (
                await lock_connection.execute(
                    text("SELECT pg_try_advisory_lock(hashtext('MafiaNew:telegram-polling'))")
                )
            ).scalar()
            if acquired:
                break
            logger.warning("Another MafiaNew instance owns the Telegram polling lock; waiting...")
            await asyncio.sleep(5)

        logger.info("Telegram polling lock acquired")
        await asyncio.gather(run_bot(), run_http())
