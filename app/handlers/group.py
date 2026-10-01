from aiogram import Router
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


@router.message(commands={"newgame"})
async def new_game_handler(message: Message) -> None:
    if not message.chat or message.chat.type not in ("group", "supergroup"):
        await message.answer("این دستور فقط داخل گروه قابل استفاده است.")
        return
    if not message.from_user:
        return

    async with session_factory() as session:
        group = await GroupRepository.upsert_from_chat(session, message.chat)
        active = await GameRepository.get_active(session, group.id)
        if active:
            await message.answer("در این گروه یک بازی فعال وجود دارد.")
            return

        result = await session.execute(
            select(Scenario).where(Scenario.key == "classic", Scenario.enabled.is_(True))
        )
        scenario = result.scalar_one_or_none()
        if scenario is None:
            await message.answer("سناریوی کلاسیک هنوز در پایگاه داده ثبت نشده است.")
            return

        game = await create_game(session, group, scenario)
        user = await UserRepository.upsert_from_telegram(session, message.from_user)
        await GameRepository.join(session, game, user)
        text = await render_lobby(session, game)
        await message.answer(text, reply_markup=lobby_keyboard(game.game_key, can_start=False))


@router.message(commands={"mafia"})
async def mafia_menu_handler(message: Message) -> None:
    await message.answer("برای ساخت بازی از /newgame استفاده کنید.")
