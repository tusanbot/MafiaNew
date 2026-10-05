import asyncio
import logging
import uvicorn
from sqlalchemy import text
from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand, BotCommandScopeAllGroupChats, BotCommandScopeAllPrivateChats
from app.config import get_settings
from app.db.session import engine
from app.handlers import register_handlers
from app.health import app as health_app
from app.logging import configure_logging
from app.services.rich_message import install_rich_message_transport
from app.services.birthday import run_birthday_announcements

async def _register_bot_commands(bot: Bot) -> None:
    """Publish the command menu Telegram clients use for slash-command suggestions."""
    private_commands = [
        BotCommand(command="start", description="شروع و نمایش منوی اصلی"),
        BotCommand(command="profile", description="نمایش پروفایل و آمار"),
        BotCommand(command="ranking", description="رتبه‌بندی بازیکنان"),
        BotCommand(command="achievements", description="نمایش دستاوردها"),
        BotCommand(command="admin", description="پنل مدیریت ربات"),
    ]
    group_commands = [
        BotCommand(command="start", description="ثبت/مدیریت گروه"),
        BotCommand(command="mafia", description="منوی مافیا"),
        BotCommand(command="newgame", description="ساخت بازی جدید"),
        BotCommand(command="gamelocks", description="نمایش وضعیت قفل‌ها"),
        BotCommand(command="chatlock", description="فعال/غیرفعال کردن قفل چت"),
        BotCommand(command="nightlock", description="فعال/غیرفعال کردن قفل شب"),
        BotCommand(command="turnlock", description="فعال/غیرفعال کردن قفل نوبت"),
        BotCommand(command="challenge", description="ثبت درخواست چالش"),
    ]
    await bot.set_my_commands(private_commands, scope=BotCommandScopeAllPrivateChats())
    await bot.set_my_commands(group_commands, scope=BotCommandScopeAllGroupChats())
    # Keep the default scope populated as well so clients that do not resolve a
    # narrower scope still receive a useful command list.
    await bot.set_my_commands(private_commands)


async def run_bot() -> None:
    settings = get_settings()
    bot = Bot(settings.bot_token)
    install_rich_message_transport()
    try:
        await _register_bot_commands(bot)
    except Exception:
        logging.getLogger(__name__).exception("Failed to publish Telegram command menu; polling will continue.")
    dispatcher = Dispatcher()
    register_handlers(dispatcher)
    birthday_task = asyncio.create_task(run_birthday_announcements(bot))
    try:
        await dispatcher.start_polling(bot)
    finally:
        birthday_task.cancel()
        try:
            await birthday_task
        except asyncio.CancelledError:
            pass
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
