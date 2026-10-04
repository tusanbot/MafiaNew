from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
import re
import unicodedata
from sqlalchemy import select, func

from app.db.models import Game, GameEvent, GamePlayer, Group, GroupSettings, Role, User
from app.db.session import session_factory
from app.handlers.keyboards import leader_choice_keyboard, leader_settings_keyboard, main_menu
from app.repositories.games import GameRepository
from app.repositories.users import UserRepository
from app.repositories.groups import GroupRepository
from app.services.game import render_lobby
from app.services.gameplay import choose_leader, start_round, current_round, next_turn, alive_players
from app.services.profile import sync_telegram_user
from app.services.stats import leaderboard, rank_for_score, rank_progress
import json
from app.utils.text import tg_name

router = Router(name="text_commands")


_ZERO_WIDTH = re.compile(r"[\u200b\u200c\u200d\u200e\u200f\u202a-\u202e\ufeff]")

def _normalize_command_text(value: str | None) -> str:
    """Normalize Persian/Arabic text commands without changing their meaning."""
    if not value:
        return ""
    value = unicodedata.normalize("NFKC", value)
    value = _ZERO_WIDTH.sub("", value)
    value = value.replace("ي", "ی").replace("ى", "ی").replace("ك", "ک")
    return " ".join(value.strip().split())

def _exact(*values: str):
    """Exact command matching with harmless Telegram/Persian whitespace normalization."""
    normalized = {_normalize_command_text(value) for value in values}
    return lambda message: _normalize_command_text(message.text) in normalized


async def _user(session, message: Message):
    tg = message.from_user
    return await UserRepository(session).upsert_from_telegram(
        tg.id, tg.username, tg.first_name or "", tg.last_name
    )


async def _active_game(session, message: Message):
    if message.chat.type not in {"group", "supergroup"}:
        return None
    # Game.group_id references the internal groups.id, not Telegram chat_id.
    # Resolve the registered group first; passing chat.id directly makes every
    # text command behave as if there were no active game.
    group = await GroupRepository.get_by_telegram_id(session, int(message.chat.id))
    if not group:
        return None
    return await GameRepository.get_active(session, group.id)


async def _is_host(session, game, user) -> bool:
    return bool(game and user and game.host_user_id == user.id)


@router.message(_exact("پیوی", "پی وی", "پنل"))
async def text_private_panel(message: Message, state: FSMContext) -> None:
    if message.chat.type != "private":
        return
    await message.answer("👤 پنل شخصی", reply_markup=main_menu())


@router.message(_exact("پروفایل", "profile"))
async def text_profile(message: Message, state: FSMContext) -> None:
    if message.chat.type != "private" or not message.from_user:
        return
    async with session_factory() as session:
        user = await sync_telegram_user(
            session, message.from_user.id, message.from_user.username,
            message.from_user.first_name or "", message.from_user.last_name
        )
        position = (await session.scalar(
            select(func.count(User.id)).where(User.is_active.is_(True), User.score > user.score)
        ) or 0) + 1
        rank, next_score, remaining = rank_progress(user.score)
        await session.commit()
    next_text = f"تا رتبه بعد: {remaining} امتیاز" if next_score is not None else "بالاترین رتبه"
    await message.answer(
        "👤 پروفایل بازیکن\n\n"
        f"نام: {tg_name(user.display_name or user.first_name or 'بازیکن')}\n"
        f"رتبه: {rank} • جایگاه: #{position}\n"
        f"امتیاز: {user.score}\n"
        f"بازی‌ها: {user.games_played} • بردها: {user.games_won}\n"
        f"نرخ برد: {(user.games_won / user.games_played * 100) if user.games_played else 0:.1f}%\n"
        f"مافیا: {user.mafia_wins} • شهروند: {user.citizen_wins} • مستقل: {user.independent_wins}\n"
        f"چالش‌ها: {user.challenges} • کیک: {user.kicks}\n"
        f"📊 {next_text}"
    )


@router.message(_exact("رتبه", "رتبه بندی", "رتبه‌بندی", "rank", "ranking"))
async def text_ranking(message: Message, state: FSMContext) -> None:
    if message.chat.type != "private":
        return
    async with session_factory() as session:
        rows = await leaderboard(session, 10, None)
        if not rows:
            await message.answer("🏆 هنوز بازی کاملی برای رتبه‌بندی ثبت نشده است.")
            return
        lines = ["🏆 رتبه‌بندی بازیکنان", ""]
        for i, user in enumerate(rows, 1):
            lines.append(
                f"{i}. {tg_name(user.display_name or user.first_name or 'بازیکن')} — "
                f"{user.score} امتیاز — {rank_for_score(user.score)}"
            )
    await message.answer("\n".join(lines))


@router.message(_exact("نقش", "نقش من", "role", "myrole"))
async def text_role(message: Message, state: FSMContext) -> None:
    if message.chat.type != "private" or not message.from_user:
        return
    async with session_factory() as session:
        user = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
        if not user:
            await message.answer("هنوز پروفایلی برای شما ثبت نشده است.")
            return
        player_row = (await session.execute(
            select(GamePlayer).where(
                GamePlayer.user_id == user.id,
                GamePlayer.is_reserved.is_(False),
                GamePlayer.alive.is_(True),
            ).order_by(GamePlayer.id.desc()).limit(1)
        )).scalar_one_or_none()
        if not player_row:
            await message.answer("در حال حاضر در بازی فعالی نیستید.")
            return
        game = await session.get(Game, player_row.game_id)
        role = await session.get(Role, player_row.role_id) if player_row.role_id else None
        if not game or game.status != "running":
            await message.answer("در حال حاضر در بازی فعالی نیستید.")
            return
        if not role:
            await message.answer("نقش شما هنوز برای این بازی ثبت نشده است.")
            return
        side = {"mafia": "مافیا", "citizen": "شهروند", "independent": "مستقل"}.get(role.team, role.team)
    await message.answer(f"🎭 نقش شما\n\nنقش: {role.name_fa}\nساید: {side}")


@router.message(_exact("حاضری"))
async def text_readiness(message: Message, state: FSMContext) -> None:
    if message.chat.type not in {"group", "supergroup"}:
        return
    async with session_factory() as session:
        game = await _active_game(session, message)
        if not game or game.status != "running" or game.phase != "setup":
            await message.answer("الان زمان اعلام حاضری نیست.")
            return
        from app.handlers.gameplay import send_readiness_message
        await send_readiness_message(message.bot, session, game, message.chat.id)


@router.message(_exact("بازیکنان"))
async def text_players(message: Message, state: FSMContext) -> None:
    if message.chat.type not in {"group", "supergroup"}:
        return
    async with session_factory() as session:
        game = await _active_game(session, message)
        if not game:
            await message.answer("بازی فعالی وجود ندارد.")
            return
        players = await GameRepository.players(session, game.id)
        reserves = await GameRepository.reserves(session, game.id)
        lines = ["👥 بازیکنان حاضر", ""]
        for player, user in players:
            lines.append(f"{player.seat}. {tg_name(user.display_name or user.first_name or 'بازیکن')}")
        if reserves:
            lines += ["", "🔁 جایگزین‌ها"]
            for player, user in reserves:
                lines.append(f"{player.reserve_position}. {tg_name(user.display_name or user.first_name or 'بازیکن')}")
    await message.answer("\n".join(lines))


@router.message(_exact("لابی"))
async def text_lobby(message: Message, state: FSMContext) -> None:
    if message.chat.type not in {"group", "supergroup"}:
        return
    async with session_factory() as session:
        game = await _active_game(session, message)
        if not game or game.status != "waiting":
            await message.answer("لابی فعالی وجود ندارد.")
            return
        text, _ = await render_lobby(session, game)
    await message.answer(text)


@router.message(_exact("انتخاب سردست", "سردست"))
async def text_leader_menu(message: Message, state: FSMContext) -> None:
    if message.chat.type not in {"group", "supergroup"} or not message.from_user:
        return
    async with session_factory() as session:
        game = await _active_game(session, message)
        user = await _user(session, message)
        if not await _is_host(session, game, user) or game.phase != "setup":
            await message.answer("فقط گرداننده و فقط در مرحله آماده‌سازی می‌تواند سردست را انتخاب کند.")
            return
        players = await GameRepository.players(session, game.id)
    await message.answer(
        "👑 انتخاب سردست\n\nروش انتخاب را مشخص کنید:",
        reply_markup=leader_choice_keyboard(game.game_key, players),
    )


@router.message(_exact("تنظیمات بازی"))
async def text_game_settings(message: Message, state: FSMContext) -> None:
    if message.chat.type not in {"group", "supergroup"} or not message.from_user:
        return
    async with session_factory() as session:
        game = await _active_game(session, message)
        user = await _user(session, message)
        if not await _is_host(session, game, user):
            await message.answer("فقط گرداننده می‌تواند تنظیمات بازی را باز کند.")
            return
        from app.handlers.keyboards import game_features_menu
        markup = game_features_menu(
            game.group_id, game.challenge_enabled, game.challenge_mode,
            game.next_host_enabled, game.next_player_enabled, game.next_auto_enabled,
            game.auto_silence_warnings, game.auto_kick_warnings,
            game.turn_seconds, game.challenge_seconds, game.extra_challenge_seconds,
        )
    await message.answer("⚙️ تنظیمات بازی", reply_markup=markup)


@router.message(_exact("شروع دور"))
async def text_start_round(message: Message, state: FSMContext) -> None:
    if message.chat.type not in {"group", "supergroup"} or not message.from_user:
        return
    async with session_factory() as session:
        game = await _active_game(session, message)
        user = await _user(session, message)
        if not await _is_host(session, game, user):
            await message.answer("فقط گرداننده می‌تواند دور را شروع کند.")
            return
        try:
            result = await start_round(session, game)
        except ValueError as exc:
            await message.answer(str(exc))
            return
        from app.handlers.gameplay import (
            update_round_roster,
            update_main_roster,
            _send_turn_message,
            _schedule_auto_next,
        )
        await update_main_roster(message.bot, session, game, message.chat.id)
        await update_round_roster(message.bot, session, game, message.chat.id)
        turn = await __import__("app.services.gameplay", fromlist=["current_turn"]).current_turn(
            session, game.id
        )
        if turn:
            await _send_turn_message(message.bot, session, game, message.chat.id, turn)
            await _schedule_auto_next(message.bot, game.game_key, message.chat.id)


@router.message(_exact("لغو بازی"))
async def text_cancel_game(message: Message, state: FSMContext) -> None:
    if message.chat.type not in {"group", "supergroup"} or not message.from_user:
        return
    async with session_factory() as session:
        game = await _active_game(session, message)
        user = await _user(session, message)
        if not await _is_host(session, game, user):
            await message.answer("فقط گرداننده می‌تواند بازی را لغو کند.")
            return
        await GameRepository.cancel(session, game)
        from app.handlers.gameplay import delete_main_roster, release_global_lock
        await release_global_lock(message.bot, session, game)
        await delete_main_roster(message.bot, session, game)
    await message.answer("❌ بازی توسط گرداننده لغو شد.")





async def _is_group_manager(bot, session, game, message: Message, require_host: bool = False) -> bool:
    if not message.from_user or not game:
        return False
    user = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
    if require_host:
        return bool(user and game.host_user_id == user.id)
    if user and game.host_user_id == user.id:
        return True
    try:
        member = await bot.get_chat_member(message.chat.id, message.from_user.id)
        return member.status in {"creator", "administrator"}
    except Exception:
        return False


async def _reply_target(message: Message, session, game):
    if not message.reply_to_message or not message.reply_to_message.from_user:
        return None, "این دستور باید در پاسخ به پیام همان بازیکن ارسال شود."
    target = await session.scalar(
        select(User).where(User.telegram_id == message.reply_to_message.from_user.id)
    )
    if not target:
        return None, "بازیکن پیدا نشد."
    player = await session.scalar(
        select(GamePlayer).where(GamePlayer.game_id == game.id, GamePlayer.user_id == target.id)
    )
    if not player or player.is_reserved:
        return None, "کاربر پاسخ‌داده‌شده بازیکن این بازی نیست."
    return (player, target), None




def _turn_duration_local(game, kind: str) -> int:
    if kind == "challenge":
        return int(getattr(game, "challenge_seconds", 60) or 60)
    if kind == "extra":
        return int(getattr(game, "extra_challenge_seconds", 60) or 60)
    return int(getattr(game, "turn_seconds", 120) or 120)


def _format_duration(seconds: int) -> str:
    minutes, remainder = divmod(max(0, int(seconds)), 60)
    return f"{minutes:02d}:{remainder:02d}"


async def _refresh_roster(bot, session, game, chat_id: int | None = None):
    try:
        from app.handlers.gameplay import update_round_roster, update_main_roster
        if chat_id:
            await update_main_roster(bot, session, game, chat_id)
            await update_round_roster(bot, session, game, chat_id)
    except Exception:
        pass


@router.message(lambda m: bool(m.text) and _normalize_command_text(m.text).startswith("حذف تذکر"))
async def text_remove_warning(message: Message, state: FSMContext) -> None:
    if message.chat.type not in {"group", "supergroup"}:
        return
    if not message.reply_to_message:
        await message.answer("این دستور باید به پیام بازیکن ریپلای شود.")
        return
    command = _normalize_command_text(message.text)
    parts = command.split()
    if parts[0:2] != ["حذف", "تذکر"]:
        return
    if len(parts) == 1 or len(parts) == 2:
        amount = 1
    elif len(parts) == 3 and parts[2].isdigit():
        amount = int(parts[2])
        if amount <= 0:
            await message.answer("تعداد تذکر باید بیشتر از صفر باشد.")
            return
    else:
        await message.answer("فرمت درست: «حذف تذکر» یا «حذف تذکر 2»")
        return

    async with session_factory() as session:
        game = await _active_game(session, message)
        if not game or game.status not in {"waiting", "running"}:
            await message.answer("بازی فعالی وجود ندارد.")
            return
        if not await _is_group_manager(message.bot, session, game, message):
            await message.answer("فقط گرداننده بازی یا مدیر گروه می‌تواند تذکر را حذف کند.")
            return
        result, error = await _reply_target(message, session, game)
        if error:
            await message.answer(error)
            return
        target, target_user = result
        old_count = int(target.warning_count or 0)
        removed = min(amount, old_count)
        if removed <= 0:
            await message.answer("این بازیکن تذکری ندارد.")
            return
        # Warning penalties are progressive up to 5; restore the exact score
        # impact of the warnings that are removed, then lower the count.
        score_restore = sum(min(old_count - i, 5) for i in range(removed))
        target.warning_count = old_count - removed
        target_user.score += score_restore
        await session.flush()
        await _refresh_roster(message.bot, session, game, message.chat.id)
        await session.commit()
        await message.answer(
            f"➖ <b>{removed}</b> تذکر از {tg_name(target_user.display_name or target_user.first_name or 'بازیکن')} کم شد.\n"
            f"⚠️ تذکر فعلی: <b>{target.warning_count}</b>",
            parse_mode="HTML",
        )

@router.message(_exact("تذکر", "تذکر-", "کیک بازیکن", "سکوت بازیکن", "ترن اضافه", "تولد بازیکن", "حذف بازیکن"))
async def text_reply_management(message: Message, state: FSMContext) -> None:
    if message.chat.type not in {"group", "supergroup"}:
        return
    if not message.reply_to_message:
        await message.answer("این دستور باید به پیام بازیکن ریپلای شود.")
        return
    async with session_factory() as session:
        game = await _active_game(session, message)
        if not game or game.status not in {"waiting", "running"}:
            await message.answer("بازی فعالی وجود ندارد.")
            return
        if not await _is_group_manager(message.bot, session, game, message):
            await message.answer("فقط گرداننده بازی یا مدیر گروه می‌تواند این عملیات را انجام دهد.")
            return
        result, error = await _reply_target(message, session, game)
        if error:
            await message.answer(error)
            return
        target, target_user = result
        command = _normalize_command_text(message.text)
        round_no = await current_round(session, game.id) if game.status == "running" else None

        if command == "تذکر":
            target.warning_count += 1
            penalty = min(target.warning_count, 5)
            target_user.score -= penalty
            event_type, response = "warning", f"⚠️ تذکر {target.warning_count} برای {tg_name(target_user.display_name or target_user.first_name)} ثبت شد."
            if target.warning_count >= 4 and game.auto_silence_warnings and round_no is not None:
                target.silence_until_round = round_no + 1
            if target.warning_count >= 5 and game.auto_kick_warnings:
                target.alive, target.exit_type = False, "kick"
        elif command == "تذکر-":
            if target.warning_count <= 0:
                await message.answer("این بازیکن تذکری ندارد.")
                return
            target.warning_count -= 1
            target_user.score += min(target.warning_count + 1, 5)
            event_type, response = "warning_removed", f"➖ یک تذکر از {tg_name(target_user.display_name or target_user.first_name)} کم شد."
        elif command == "کیک بازیکن":
            if not target.alive:
                await message.answer("این بازیکن قبلاً از بازی خارج شده است.")
                return
            target.alive, target.exit_type = False, "kick"
            event_type, response = "player_kicked", f"⛔ {tg_name(target_user.display_name or target_user.first_name)} از بازی کیک شد."
        elif command == "سکوت بازیکن":
            if not target.alive:
                await message.answer("بازیکن زنده نیست.")
                return
            target.silence_until_round = (round_no or 0)
            event_type, response = "silence", f"🔇 {tg_name(target_user.display_name or target_user.first_name)} برای این دور ساکت شد."
        elif command == "ترن اضافه":
            if not target.alive or round_no is None:
                await message.answer("ترن اضافه فقط برای بازیکن زنده در بازی در حال اجرا قابل ثبت است.")
                return
            target.extra_turn_round = round_no
            queue_event = (await session.execute(
                select(GameEvent).where(GameEvent.game_id == game.id, GameEvent.event_type == "turn_queue").order_by(GameEvent.id.desc())
            )).scalars().first()
            if queue_event:
                data = json.loads(queue_event.payload or "{}")
                data.setdefault("queue", [])
                data.setdefault("extra_turn_users", [])
                if target.id not in data["extra_turn_users"]:
                    data["queue"].append(target.id)
                    data["extra_turn_users"].append(target.id)
                queue_event.payload = json.dumps(data, ensure_ascii=False)
            event_type, response = "extra_turn_granted", f"➕ ترن اضافه برای {tg_name(target_user.display_name or target_user.first_name)} ثبت شد."
        elif command == "تولد بازیکن":
            if game.status != "running" or target.alive or target.exit_type != "death":
                await message.answer("فقط بازیکن حذف‌شده با وضعیت مرگ قابل تولد است.")
                return
            target.alive, target.exit_type = True, None
            target.silence_until_round = None
            target.extra_turn_round = None
            event_type, response = "birthday", f"🎂 {tg_name(target_user.display_name or target_user.first_name)} به بازی بازگشت."
        else:
            if game.status == "waiting":
                await session.delete(target)
            else:
                if not target.alive:
                    await message.answer("این بازیکن قبلاً از بازی خارج شده است.")
                    return
                target.alive, target.exit_type = False, "death"
            event_type, response = "death", f"💀 {tg_name(target_user.display_name or target_user.first_name)} حذف شد."

        session.add(GameEvent(
            game_id=game.id,
            actor_user_id=(await session.scalar(select(User.id).where(User.telegram_id == message.from_user.id))),
            event_type=event_type,
            payload=json.dumps({"user_id": target.id, "command": command}, ensure_ascii=False),
        ))
        await session.commit()
        if game.status == "running":
            await _refresh_roster(message.bot, session, game, message.chat.id)
    await message.answer(response)


@router.message(_exact("پنل", "مدیریت"))
async def text_group_panel(message: Message, state: FSMContext) -> None:
    if message.chat.type not in {"group", "supergroup"} or not message.from_user:
        return
    async with session_factory() as session:
        game = await _active_game(session, message)
        user = await _user(session, message)
        if not game or not await _is_host(session, game, user):
            await message.answer("فقط گرداننده بازی می‌تواند پنل مدیریت را باز کند.")
            return
        from app.handlers.keyboards import active_game_menu
        await message.answer("🎮 پنل مدیریت بازی", reply_markup=active_game_menu(game.group_id, f"gameadmin:active:{game.group_id}", game.game_key, game.status == "waiting"))

@router.message(_exact("سکوت"))
async def text_silence_short(message: Message, state: FSMContext) -> None:
    if message.chat.type not in {"group", "supergroup"} or not message.reply_to_message:
        await message.answer("دستور «سکوت» باید روی پیام بازیکن ریپلای شود.")
        return
    message.text = "سکوت بازیکن"
    await text_reply_management(message, state)

@router.message(_exact("پایان بازی"))
async def text_finish_game(message: Message, state: FSMContext) -> None:
    if message.chat.type not in {"group", "supergroup"} or not message.from_user:
        return
    async with session_factory() as session:
        game = await _active_game(session, message)
        user = await _user(session, message)
        if not game or not await _is_host(session, game, user):
            await message.answer("فقط گرداننده می‌تواند پایان بازی را اجرا کند.")
            return
        from app.handlers.keyboards import finish_game_keyboard
        await message.answer("🏁 نتیجه نهایی بازی را انتخاب کن:", reply_markup=finish_game_keyboard(game.group_id))

@router.message(_exact("فازشب", "فاز شب"))
async def text_start_night(message: Message, state: FSMContext) -> None:
    if message.chat.type not in {"group", "supergroup"} or not message.from_user:
        return
    async with session_factory() as session:
        game = await _active_game(session, message)
        user = await _user(session, message)
        if not game or not await _is_host(session, game, user):
            await message.answer("فقط گرداننده می‌تواند فاز شب را شروع کند.")
            return
        turn = await __import__("app.services.gameplay", fromlist=["current_turn"]).current_turn(session, game.id)
        if game.phase == "day" and (not turn or turn.get("status") != "finished"):
            await message.answer("ابتدا نوبت‌های این دور را تمام کن.")
            return
        if game.phase not in {"day", "vote1_complete", "vote2_complete"}:
            await message.answer("الان امکان شروع فاز شب وجود ندارد.")
            return
        game.phase = "night"
        await session.commit()
        from app.handlers.keyboards import continue_night_keyboard
        settings = await session.scalar(select(GroupSettings).where(GroupSettings.group_id == game.group_id))
        await message.bot.send_message(
            message.chat.id,
            "🌙 فاز شب آغاز شد.",
            reply_markup=continue_night_keyboard(
                game.game_key,
                settings.night_lock if settings else False,
                settings.chat_lock if settings else False,
            ),
        )
        from app.handlers.gameplay import _send_night_menus, _set_game_chat_lock
        await _set_game_chat_lock(message.bot, session, game, bool(settings and settings.night_lock))
        await _send_night_menus(message.bot, session, game)

@router.message(_exact("جایگزین", "sub", "substitute"))
async def text_substitute(message: Message, state: FSMContext) -> None:
    if message.chat.type not in {"group", "supergroup"}:
        return
    async with session_factory() as session:
        game = await _active_game(session, message)
        if not game or game.status not in {"waiting", "running"}:
            await message.answer("بازی فعالی وجود ندارد.")
            return
        requester = message.from_user
        if not requester:
            return
        replied = message.reply_to_message.from_user if message.reply_to_message else None
        target_tg_id = replied.id if replied else requester.id
        target_user = await UserRepository(session).get_by_telegram_id(target_tg_id)
        if not target_user:
            target_user = await UserRepository(session).upsert_from_telegram(
                target_tg_id,
                replied.username if replied else requester.username,
                replied.first_name if replied else requester.first_name or "",
                replied.last_name if replied else requester.last_name,
            )
        player = await GameRepository.join_substitute(session, game, target_user)
        if not player:
            await message.answer("این بازیکن قبلاً در بازی یا لیست جایگزین ثبت شده است.")
            return
        await message.answer(
            f"🔁 {tg_name(target_user.display_name or target_user.first_name or 'بازیکن')} وارد لیست جایگزین شد.\n"
            f"📋 نوبت جایگزینی: <b>{player.substitute_position}</b>",
            parse_mode="HTML",
        )

@router.message(_exact("قفل بازی", "قفل شب", "قفل نوبت"))
async def text_toggle_lock(message: Message, state: FSMContext) -> None:
    if message.chat.type not in {"group", "supergroup"}:
        return
    async with session_factory() as session:
        game = await _active_game(session, message)
        user = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
        group = await GroupRepository.get_by_telegram_id(session, int(message.chat.id))
        if not group:
            await message.answer("این گروه هنوز در ربات ثبت نشده است.")
            return
        # Locks belong to GroupSettings, so they can be changed even when
        # there is no active game. The caller must be a group admin, or the
        # current game's host when a game exists.
        is_manager = False
        if game and user and game.host_user_id == user.id:
            is_manager = True
        if not is_manager:
            try:
                member = await message.bot.get_chat_member(message.chat.id, message.from_user.id)
                is_manager = member.status in {"creator", "administrator"}
            except Exception:
                is_manager = False
        if not is_manager:
            await message.answer("فقط گرداننده بازی یا مدیر گروه می‌تواند قفل‌ها را تغییر دهد.")
            return
        settings = await session.scalar(select(GroupSettings).where(GroupSettings.group_id == group.id))
        if not settings:
            settings = GroupSettings(group_id=group.id)
            session.add(settings)
        command = _normalize_command_text(message.text)
        field = {"قفل بازی": "chat_lock", "قفل شب": "night_lock", "قفل نوبت": "turn_lock"}[command]
        setattr(settings, field, not bool(getattr(settings, field)))
        enabled = bool(getattr(settings, field))
        await session.commit()
    await message.answer(f"{'🔒' if enabled else '🔓'} {command} {'فعال' if enabled else 'غیرفعال'} شد.")


@router.message(_exact("بعدی"))
async def text_vote_next(message: Message, state: FSMContext) -> None:
    if message.chat.type not in {"group", "supergroup"}:
        return
    async with session_factory() as session:
        game = await _active_game(session, message)
        actor = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
        if not game or not actor:
            await message.answer("بازی یا کاربر پیدا نشد.")
            return
        host = await session.get(User, game.host_user_id) if game.host_user_id else None
        if not host or actor.id != host.id:
            await message.answer("فقط گرداننده می‌تواند بازیکن بعدی را شروع کند.")
            return
        from app.handlers.gameplay import _vote_target_message, _vote_tasks
        from app.services.gameplay import advance_vote1, advance_vote2
        try:
            if game.phase == "voting1":
                result = await advance_vote1(session, game)
                if not result["finished"]:
                    await _vote_target_message(message.bot, session, game, message.chat.id)
                else:
                    await message.answer("رای اول تمام شد؛ از گزینه اتمام رای گیری استفاده کنید.")
            elif game.phase == "voting2":
                result = await advance_vote2(session, game)
                if not result["finished"]:
                    await _vote_target_message(message.bot, session, game, message.chat.id)
                else:
                    await message.answer("رای دوم تمام شد.")
            else:
                return
        except ValueError as exc:
            await message.answer(str(exc))
@router.message(_exact("نکست"))
async def text_next(message: Message, state: FSMContext) -> None:
    if message.chat.type not in {"group", "supergroup"}:
        return
    async with session_factory() as session:
        game = await _active_game(session, message)
        actor = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
        if not game or not actor:
            await message.answer("بازی یا کاربر پیدا نشد.")
            return
        turn = await __import__("app.services.gameplay", fromlist=["current_turn"]).current_turn(
            session, game.id
        )
        host = await session.get(User, game.host_user_id) if game.host_user_id else None
        if not turn:
            await message.answer("نوبت فعالی وجود ندارد.")
            return
        if not host or (actor.id != host.id and int(turn.get("user_id", -1)) != actor.id):
            await message.answer("فقط گرداننده یا صاحب نوبت فعلی می‌تواند نکست بزند.")
            return
        if actor.id == host.id and not game.next_host_enabled:
            await message.answer("نکست گرداننده غیرفعال است.")
            return
        if actor.id != host.id and not game.next_player_enabled:
            await message.answer("نکست بازیکن غیرفعال است.")
            return
        try:
            from app.handlers.gameplay import (
                _finish_turn_message,
                _delete_turn_challenge_messages,
                _send_turn_message,
                _schedule_auto_next,
                _turn_transition_locks,
            )
            lock = _turn_transition_locks.setdefault(game.game_key, __import__("asyncio").Lock())
            async with lock:
                fresh_turn = await __import__("app.services.gameplay", fromlist=["current_turn"]).current_turn(session, game.id)
                if not fresh_turn or fresh_turn.get("status") not in ("active", "paused"):
                    await message.answer("این نوبت قبلاً رد شده است.")
                    return
                if (
                    fresh_turn.get("kind") != turn.get("kind")
                    or int(fresh_turn.get("user_id", -1)) != int(turn.get("user_id", -1))
                    or fresh_turn.get("started_at") != turn.get("started_at")
                ):
                    await message.answer("این نوبت قبلاً رد شده است.")
                    return
                turn = fresh_turn
                await _finish_turn_message(message.bot, session, game, turn)
                await _delete_turn_challenge_messages(message.bot, session, game, turn)
                result = await next_turn(session, game)
        except ValueError as exc:
            await message.answer(str(exc))
            return
        chat_id = message.chat.id
        if result["kind"] == "finished_day":
            await message.bot.send_message(
                chat_id,
                "🗳 نوبت‌های این دور تمام شد. آماده رأی‌گیری هستید.",
                reply_markup=__import__("app.handlers.keyboards", fromlist=["day_keyboard"]).day_keyboard(
                    game.game_key, await alive_players(session, game.id)
                ),
            )
        else:
            new_turn = await __import__("app.services.gameplay", fromlist=["current_turn"]).current_turn(
                session, game.id
            )
            if new_turn:
                await _send_turn_message(message.bot, session, game, chat_id, new_turn)
                await _schedule_auto_next(message.bot, game.game_key, chat_id)


@router.message(_exact("دستورات", "دستورها"))
async def text_commands(message: Message, state: FSMContext) -> None:
    lines = [
        "📚 <b>دستورات متنی</b>",
        "",
        "پیوی:",
        "<code>پنل</code> — باز کردن پنل شخصی",
        "<code>پروفایل</code> — نمایش پروفایل",
        "<code>نقش من</code> — نمایش نقش بازی فعلی",
        "<code>رتبه</code> — نمایش رتبه‌بندی",
        "",
        "بازی:",
        "<code>لابی</code> — نمایش لابی",
        "<code>بازیکنان</code> — نمایش بازیکنان و جایگزین‌ها",
        "<code>جایگزین</code> — ورود شما یا بازیکن ریپلای‌شده به لیست جایگزین",
        "<code>انتخاب سردست</code> — انتخاب سردست",
        "<code>تنظیمات بازی</code> — باز کردن تنظیمات",
        "<code>شروع دور</code> — شروع دور",
        "<code>لغو بازی</code> — لغو بازی",
        "",
        "کنترل:",
        "<code>نکست</code> — رفتن به نوبت بعد",
        "<code>بعدی</code> — رفتن به بازیکن بعدی رأی‌گیری",
        "<code>قفل بازی</code> — روشن/خاموش کردن قفل چت",
        "<code>قفل شب</code> — روشن/خاموش کردن قفل شب",
        "<code>قفل نوبت</code> — روشن/خاموش کردن قفل نوبت",
        "",
        "مدیریت بازیکن — روی پیام بازیکن ریپلای کن:",
        "<code>تذکر</code> — ثبت تذکر",
        "<code>تذکر-</code> — حذف یک تذکر",
        "<code>کیک بازیکن</code> — خروج بازیکن با کیک",
        "<code>سکوت بازیکن</code> — ساکت کردن بازیکن برای این دور",
        "<code>ترن اضافه</code> — دادن ترن اضافه",
        "<code>تولد بازیکن</code> — بازگرداندن بازیکن کشته‌شده",
        "<code>حذف بازیکن</code> — حذف بازیکن",
    ]
    await message.answer("\n".join(lines), parse_mode="HTML")
