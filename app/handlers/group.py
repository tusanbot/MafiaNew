from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy import select

from app.db.session import session_factory
from app.db.models import Scenario, GroupSettings, User
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


@router.message(lambda m: bool(m.text) and m.text.strip() in {"/newgame", "بازی جدید"})
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
        group = await GroupRepository.get_by_telegram_id(session, message.chat.id)
        if not group or not group.is_active or group.registered_at is None:
            await message.answer("این گروه هنوز در ربات ثبت نشده است. از /start داخل گروه برای ثبت گروه استفاده کنید.")
            return
        active = await GameRepository.get_active(session, group.id)
        if active:
            await message.answer("در این گروه یک بازی فعال وجود دارد.")
            return

        result = await session.execute(
            select(Scenario).where(Scenario.enabled.is_(True)).order_by(Scenario.id)
        )
        scenario = result.scalars().first()
        if scenario is None:
            await message.answer("هیچ سناریوی فعالی برای ایجاد بازی ثبت نشده است.")
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


@router.message(lambda m: bool(m.text) and m.text.strip().lstrip("/") == "جایگزین")
async def reserve_text_handler(message: Message) -> None:
    if message.chat.type not in ("group", "supergroup") or not message.from_user:
        return
    if message.reply_to_message and message.reply_to_message.from_user:
        if not await is_group_admin(message):
            await message.answer("افزودن فرد دیگر به لیست رزرو فقط برای مدیر گروه مجاز است.")
            return
        target_tg = message.reply_to_message.from_user.id
        target_tg_user = message.reply_to_message.from_user
    else:
        target_tg = message.from_user.id
        target_tg_user = message.from_user
    async with session_factory() as session:
        group = await GroupRepository.get_by_telegram_id(session, message.chat.id)
        game = await GameRepository.get_active(session, group.id) if group else None
        if not game or game.status != "waiting":
            await message.answer("در حال حاضر بازی در مرحله‌ای نیست که لیست رزرو قابل ثبت باشد.")
            return
        user = await UserRepository(session).upsert_from_telegram(
            target_tg, target_tg_user.username, target_tg_user.first_name or "", target_tg_user.last_name
        )
        player = await GameRepository.join_reserve(session, game, user)
        if not player:
            await message.answer("ثبت در لیست رزرو انجام نشد؛ ظرفیت اصلی باید تکمیل باشد یا شما قبلاً در بازی هستید.")
            return
        await message.answer(
            f"بازیکن {user.display_name or user.first_name} با شماره رزرو {player.reserve_position} وارد لیست جایگزین شد."
        )


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
            "تنظیمات قفل بازی:\n"
            f"قفل چت: {'فعال' if settings.chat_lock else 'غیرفعال'}\n"
            f"قفل شب: {'فعال' if settings.night_lock else 'غیرفعال'}\n"
            f"قفل نوبت: {'فعال' if settings.turn_lock else 'غیرفعال'}\n\n"
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


@router.message(Command("challenge"))
async def challenge_command(message: Message) -> None:
    if message.chat.type not in ("group", "supergroup") or not message.from_user:
        return
    async with session_factory() as session:
        group = await GroupRepository.get_by_telegram_id(session, message.chat.id)
        if not group:
            await message.answer("گروه ثبت نشده است.")
            return
        game = await GameRepository.get_active(session, group.id)
        if not game or game.phase != "day":
            await message.answer("درخواست چالش فقط در مرحله روز بازی فعال است.")
            return
        challenger = await UserRepository(session).upsert_from_telegram(
            message.from_user.id, message.from_user.username,
            message.from_user.first_name or "", message.from_user.last_name
        )
        from app.services.gameplay import submit_challenge
        try:
            result = await submit_challenge(session, game, challenger)
        except ValueError as exc:
            await message.answer(str(exc))
            return
        owner = await session.get(User, result["turn_user_id"])
        if owner:
            await message.answer(
                f"درخواست چالش ثبت شد و برای صاحب نوبت {owner.display_name or owner.first_name} ارسال شد."
            )
        else:
            await message.answer("درخواست چالش ثبت شد.")

@router.message()
async def game_chat_lock_guard(message: Message) -> None:
    if message.chat.type not in ("group", "supergroup") or not message.from_user:
        return
    if message.text and message.text.startswith("/"):
        return
    async with session_factory() as session:
        group = await GroupRepository.get_by_telegram_id(session, message.chat.id)
        if not group:
            return
        game = await GameRepository.get_active(session, group.id)
        if not game or game.status != "running":
            return
        settings = (await session.execute(
            select(GroupSettings).where(GroupSettings.group_id == group.id)
        )).scalar_one_or_none()
        if not settings:
            return
        turn = None
        if settings.turn_lock and game.phase == "day":
            from app.services.gameplay import current_turn
            turn = await current_turn(session, game.id)
        locked = settings.chat_lock or (settings.night_lock and game.phase == "night") or (settings.turn_lock and game.phase == "day" and turn and int(turn.get("user_id", -1)) != message.from_user.id)
        if not locked:
            return
        member = await message.bot.get_chat_member(message.chat.id, message.from_user.id)
        if member.status in ("creator", "administrator"):
            return
        try:
            await message.delete()
        except Exception:
            pass
