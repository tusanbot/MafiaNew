from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message
router = Router(name="common")

@router.message(CommandStart())
async def start_handler(message: Message) -> None:
    name = message.from_user.first_name if message.from_user else "دوست"
    await message.answer(f"سلام {name}\n\nبه ربات مافیا خوش آمدی.\nنسخه جدید در حال توسعه است.")
