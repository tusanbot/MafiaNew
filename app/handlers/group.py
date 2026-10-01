from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy import select

from app.db.session import session_factory
from app.db.models import Scenario, GroupSettings
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


@router.message(Command("gamelocks"))
async def game_locks_handler(message: Message) -> None:
    if message.chat.type not in ("group", "supergroup") or not await is_group_admin(message):
        return
    async with session_factory() as session:
        group = await GroupRepository.get_by_telegram_id(session, message.chat.id)
        if not group:
            await message.answer("ابتدا یک بازی بسازید یا گروه را با /newgame ثبت کنید.")
            return
        settings = (await session.execute(
            select(GroupSettings).where(GroupSettings.group_id == group.id)
        )).scalar_one_or_none()
        if not settings:
            settings = GroupSettings(group_id=group.id)
            session.add(settings)
            await session.commit()
        await message.answer(
            "تنظیمات قفل بازی:
"
            f"قفل چت: {'فعال' if settings.chat_lock else 'غیرفعال'}
"
            f"قفل شب: {'فعال' if settings.night_lock else 'غیرفعال'}
"
            f"قفل نوبت: {'فعال' if settings.turn_lock else 'غیرفعال'}

"
            "برای تغییر: /chatlock on|off ، /nightlock on|off ، /turnlock on|off"
        )

async def _set_lock(message: Message, field: str, value: str) -> None:
    if message.chat.type not in ("group", "supergroup") or not await is_group_admin(message):
        return
    enabled = value.lower() in ("on", "1", "true", "فعال")
    if value.lower() not in ("on", "off", "1", "0", "true", "false", "فعال", "غیرفعال"):
        await message.answer("مقدار باید on یا off باشد.")
        return
    async with session_factory() as session:
        group = await GroupRepository.get_by_telegram_id(session, message.chat.id)
        if not group:
            await message.answer("گروه ثبت نشده است.")
            return
        settings = (await session.execute(
            select(GroupSettings).where(GroupSettings.group_id == group.id)
        )).scalar_one_or_none()
        if not settings:
            settings = GroupSettings(group_id=group.id)
            session.add(settings)
        setattr(settings, field, enabled)
        await session.commit()
    await message.answer(f"تنظیم {'فعال' if enabled else 'غیرفعال'} شد.")

@router.message(Command("chatlock"))
async def chat_lock_handler(message: Message, command: CommandObject) -> None:
    await _set_lock(message, "chat_lock", command.args or "")

@router.message(Command("nightlock"))
async def night_lock_handler(message: Message, command: CommandObject) -> None:
    await _set_lock(message, "night_lock", command.args or "")

@router.message(Command("turnlock"))
async def turn_lock_handler(message: Message, command: CommandObject) -> None:
    await _set_lock(message, "turn_lock", command.args or "")
