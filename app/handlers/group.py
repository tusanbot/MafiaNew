from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import select

from app.db.session import session_factory
from app.db.models import Scenario
from app.repositories.games import GameRepository
from app.repositories.groups import GroupRepository
from app.repositories.users import UserRepository
from app.services.game import create_game, render_lobby
from app.handlers.keyboards import lobby_keyboard

router = Router(name="group")


async def is_group_admin(message: Message) -> bool:
    if not message.from_user:
        return False
    member = await message.bot.get_chat_member(message.chat.id, message.from_user.id)
    return member.status in ("creator", "administrator")


@router.message(Command("newgame"))
async def new_game_handler(message: Message) -> None:
    if message.chat.type not in ("group", "supergroup"):
        await message.answer("این دستور فقط داخل گروه قابل استفاده است.")
        return
    if not message.from_user:
        return
    if not await is_group_admin(message):
        await message.answer("ساخت بازی فقط برای مدیران گروه فعال است.")
        return

    async with session_factory() as session:
        group = await GroupRepository.upsert_from_chat(session, message.chat)
        active = await GameRepository.get_active(session, group.id)
        if active:
            await message.answer("در این گروه یک بازی فعال وجود دارد.")
            return

        result = await session.execute(
            select(Scenario).where(
                Scenario.key == "classic", Scenario.enabled.is_(True)
            )
        )
        scenario = result.scalar_one_or_none()
        if scenario is None:
            await message.answer("سناریوی کلاسیک هنوز در پایگاه داده ثبت نشده است.")
            return

        user = await UserRepository(session).upsert_from_telegram(
            message.from_user.id,
            message.from_user.username,
            message.from_user.first_name or "",
            message.from_user.last_name,
        )
        await session.commit()
        game = await create_game(session, group, scenario, user)
        await GameRepository.join(session, game, user)
        text, can_start = await render_lobby(session, game)
        await message.answer(text, reply_markup=lobby_keyboard(game.game_key, can_start))


@router.message(Command("mafia"))
async def mafia_menu_handler(message: Message) -> None:
    await message.answer("برای ساخت بازی در گروه، /newgame را اجرا کنید.")
