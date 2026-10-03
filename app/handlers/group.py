from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup
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
    try:
        member = await message.bot.get_chat_member(message.chat.id, message.from_user.id)
        return member.status in ("creator", "administrator")
    except Exception:
        return False


async def is_group_manager(message: Message) -> bool:
    """Allow Telegram admins and the current game's host to manage game locks."""
    if await is_group_admin(message):
        return True
    if not message.from_user or message.chat.type not in ("group", "supergroup"):
        return False
    async with session_factory() as session:
        group = await GroupRepository.get_by_telegram_id(session, message.chat.id)
        if not group:
            return False
        game = await GameRepository.get_active(session, group.id)
        if not game or not game.host_user_id:
            return False
        user = await session.scalar(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        return bool(user and user.id == game.host_user_id)


@router.message(Command("newgame"))
@router.message(lambda m: bool(m.text) and m.text.strip() == "بازی جدید")
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
    if message.chat.type not in ("group", "supergroup") or not await is_group_manager(message):
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
            "🔐 وضعیت قفل‌ها\n\n"
            f"🌙 قفل شب: {'🟢 فعال' if settings.night_lock else '⚪ غیرفعال'}\n"
            f"🎮 قفل بازی: {'🟢 فعال' if settings.chat_lock else '⚪ غیرفعال'}\n"
            f"🗣 قفل نوبت: {'🟢 فعال' if settings.turn_lock else '⚪ غیرفعال'}\n\n"
            "قفل شب = بستن کامل تایپ اعضا در شب\n"
            "قفل بازی = فقط بازیکنان بازی اجازه ارسال پیام دارند\n"
            "قفل نوبت = فقط صاحب نوبت فعال اجازه ارسال پیام دارد"
        )

async def _set_lock(message: Message, field: str, value: str) -> None:
    if message.chat.type not in ("group", "supergroup") or not await is_group_manager(message):
        return
    normalized = (value or "").strip().lower()
    if normalized:
        enabled = normalized in ("on", "1", "true", "فعال")
        if normalized not in ("on", "off", "1", "0", "true", "false", "فعال", "غیرفعال"):
            await message.answer("مقدار باید on یا off باشد.")
            return
    else:
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
            enabled = not bool(getattr(settings, field))
            setattr(settings, field, enabled)
            await session.commit()
        await message.answer(f"🔐 {'فعال' if enabled else 'غیرفعال'} شد.")
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
    await message.answer(f"🔐 {'فعال' if enabled else 'غیرفعال'} شد.")

@router.message(Command("chatlock"))
async def chat_lock_handler(message: Message, command: CommandObject) -> None:
    await _set_lock(message, "chat_lock", command.args or "")

@router.message(Command("nightlock"))
async def night_lock_handler(message: Message, command: CommandObject) -> None:
    await _set_lock(message, "night_lock", command.args or "")

@router.message(Command("turnlock"))
async def turn_lock_handler(message: Message, command: CommandObject) -> None:
    await _set_lock(message, "turn_lock", command.args or "")

@router.message(lambda m: bool(m.text) and m.text.strip() in {"قفل بازی", "قفل شب", "قفل نوبت"})
async def persian_lock_handler(message: Message) -> None:
    mapping = {"قفل بازی": "chat_lock", "قفل شب": "night_lock", "قفل نوبت": "turn_lock"}
    await _set_lock(message, mapping[message.text.strip()], "")

@router.message(lambda m: bool(m.text) and m.text.strip() == "قفل کل")
async def global_lock_command(message: Message) -> None:
    if message.chat.type not in ("group", "supergroup") or not await is_group_manager(message):
        return
    async with session_factory() as session:
        group = await GroupRepository.get_by_telegram_id(session, message.chat.id)
        game = await GameRepository.get_active(session, group.id) if group else None
        if not game or game.status != "running":
            await message.answer("🔐 قفل کل فقط هنگام اجرای بازی قابل فعال‌سازی است.")
            return
        await message.answer(
            "⚠️ <b>تأیید قفل کل</b>\n\n"
            "با فعال‌سازی این قفل، مدیرانی که عضو همین بازی هستند و گرداننده نیستند، "
            "موقتاً از مدیریت گروه عزل می‌شوند.\n\n"
            "🔄 با پایان یا لغو بازی، مدیریت آن‌ها برمی‌گردد.\n"
            "👑 گرداننده تحت تأثیر این قفل نیست.\n\n"
            "آیا مطمئنی؟",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="🔒 بله، فعالش کن", callback_data=f"globallock:confirm:{game.game_key}"),
                InlineKeyboardButton(text="❌ انصراف", callback_data=f"globallock:cancel:{game.game_key}"),
            ]]),
            parse_mode="HTML",
        )

@router.callback_query(lambda c: c.data and c.data.startswith("globallock:"))
async def global_lock_callback(callback) -> None:
    if not callback.from_user or not callback.message:
        return
    parts = callback.data.split(":")
    if len(parts) != 3:
        return
    action, key = parts[1], parts[2]
    async with session_factory() as session:
        game = await GameRepository.get_by_key(session, key)
        actor = await session.scalar(select(User).where(User.telegram_id == callback.from_user.id)) if game else None
        if not game or not actor or game.host_user_id != actor.id:
            await callback.answer("فقط گرداننده می‌تواند قفل کل را تأیید کند.", show_alert=True)
            return
        if action == "cancel":
            await callback.message.edit_text("❌ قفل کل لغو شد.")
            await callback.answer()
            return
        try:
            from app.handlers.gameplay import activate_global_lock
            result = await activate_global_lock(callback.bot, session, game)
        except Exception as exc:
            await callback.answer(f"فعال‌سازی قفل کل انجام نشد: {exc}", show_alert=True)
            return
        demoted = len(result.get("demoted", []))
        failed = len(result.get("failed", []))
        text = (
            "🔒 <b>قفل کل فعال شد</b>\n\n"
            f"👥 مدیران عزل‌شده: {demoted}\n"
            f"⚠️ قابل عزل نبودند: {failed}\n\n"
            "با پایان یا لغو بازی، دسترسی مدیران برمی‌گردد."
        )
        await callback.message.edit_text(text, parse_mode="HTML")
        await callback.answer("قفل کل فعال شد.")
@router.message(Command("challenge"))
@router.message(lambda m: bool(m.text) and m.text.strip() in {"چالش", "درخواست چالش"})
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
