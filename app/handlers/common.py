from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from app.db.session import session_factory
from app.services.profile import sync_telegram_user
from app.handlers.keyboards import main_menu

router = Router(name="common")

@router.message(CommandStart())
async def start_handler(message: Message) -> None:
    if not message.from_user:
        return
    async with session_factory() as session:
        user = await sync_telegram_user(
            session,
            message.from_user.id,
            message.from_user.username,
            message.from_user.first_name or "",
            message.from_user.last_name,
        )
    await message.answer(
        f"سلام {user.display_name or 'دوست'}\n\n"
        "به ربات مافیا خوش آمدی.\n"
        "از منوی زیر بخش موردنظر را انتخاب کن.",
        reply_markup=main_menu(),
    )
