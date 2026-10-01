from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.db.session import session_factory
from app.services.profile import sync_telegram_user

router = Router(name="profile")

@router.message(Command("profile"))
async def profile_handler(message: Message) -> None:
    user = message.from_user
    if not user:
        return
    async with session_factory() as session:
        db_user = await sync_telegram_user(
            session,
            user.id,
            user.username,
            user.first_name or "",
            user.last_name,
        )
        username = f"@{db_user.username}" if db_user.username else "بدون نام کاربری"
        await message.answer(
            "پروفایل شما\n\n"
            f"نام: {db_user.display_name or 'ثبت نشده'}\n"
            f"نام کاربری: {username}\n\n"
            f"بازی‌ها: {db_user.games_played}\n"
            f"بردها: {db_user.games_won}\n"
            f"چالش‌ها: {db_user.challenges}"
        )
