import asyncio
import logging
import uvicorn
from aiogram import Bot, Dispatcher
from app.config import get_settings
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
    logging.getLogger(__name__).info("Starting Mafia Bot")
    await asyncio.gather(run_bot(), run_http())
