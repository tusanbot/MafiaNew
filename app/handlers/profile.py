from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
router = Router(name="profile")

@router.message(Command("profile"))
async def profile_handler(message: Message) -> None:
    user = message.from_user
    if not user:
        return
    username = f"@{user.username}" if user.username else "بدون نام کاربری"
    display_name = " ".join(p for p in [user.first_name, user.last_name] if p)
    await message.answer(
        "پروفایل شما\n\n"
        f"نام: {display_name or 'ثبت نشده'}\n"
        f"نام کاربری: {username}\n"
        f"شناسه تلگرام: {user.id}\n\n"
        "آمار بازی و دستاوردها به پروفایل متصل خواهد شد."
    )
