from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy import select, func

from app.db.models import Game, GameEvent, GamePlayer, Group, GroupSettings, Role, User
from app.db.session import session_factory
from app.handlers.keyboards import leader_choice_keyboard, leader_settings_keyboard, main_menu
from app.repositories.games import GameRepository
from app.repositories.users import UserRepository
from app.services.game import render_lobby
from app.services.gameplay import choose_leader, start_round, current_round, next_turn, alive_players
from app.services.profile import sync_telegram_user
from app.services.stats import leaderboard, rank_for_score, rank_progress
import json
from app.utils.text import tg_name

router = Router(name="text_commands")


def _exact(*values: str):
    """Exact text only. Never use startswith/contains for public commands."""
    return F.text.in_(values)


async def _user(session, message: Message):
    tg = message.from_user
    return await UserRepository(session).upsert_from_telegram(
        tg.id, tg.username, tg.first_name or "", tg.last_name
    )


async def _active_game(session, message: Message):
    if message.chat.type not in {"group", "supergroup"}:
        return None
    return await GameRepository.get_active(session, int(message.chat.id))


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


@router.message(_exact("حاضری", "بازیکنان"))
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
    await message.answer("👑 انتخاب سردست\n\nروش انتخاب را مشخص کنید:", reply_markup=leader_choice_keyboard(game.game_key, []))


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
    await message.answer(f"▶️ دور {result['round_no']} شروع شد.")


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
        from app.handlers.gameplay import update_round_roster
        if chat_id:
            await update_round_roster(bot, session, game, chat_id)
    except Exception:
        pass


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
        command = message.text.strip()
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


@router.message(_exact("قفل بازی", "قفل شب", "قفل نوبت"))
async def text_toggle_lock(message: Message, state: FSMContext) -> None:
    if message.chat.type not in {"group", "supergroup"}:
        return
    async with session_factory() as session:
        game = await _active_game(session, message)
        if not game:
            await message.answer("بازی فعالی وجود ندارد.")
            return
        if not await _is_group_manager(message.bot, session, game, message):
            await message.answer("فقط گرداننده بازی یا مدیر گروه می‌تواند قفل‌ها را تغییر دهد.")
            return
        user = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
        group = await session.get(Group, game.group_id)
        settings = await session.scalar(select(GroupSettings).where(GroupSettings.group_id == group.id))
        if not settings:
            settings = GroupSettings(group_id=group.id)
            session.add(settings)
        field = {"قفل بازی": "chat_lock", "قفل شب": "night_lock", "قفل نوبت": "turn_lock"}[message.text.strip()]
        setattr(settings, field, not bool(getattr(settings, field)))
        enabled = bool(getattr(settings, field))
        await session.commit()
    await message.answer(f"{'🔒' if enabled else '🔓'} {message.text.strip()} {'فعال' if enabled else 'غیرفعال'} شد.")


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
        turn = await __import__("app.services.gameplay", fromlist=["current_turn"]).current_turn(session, game.id)
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
            result = await next_turn(session, game)
        except ValueError as exc:
            await message.answer(str(exc))
            return
        chat_id = message.chat.id
        if result["kind"] == "finished_day":
            await message.bot.send_message(chat_id, "نوبت‌های این دور تمام شد. اکنون رأی‌گیری را شروع کنید.")
        else:
            user = await session.get(User, result["user_id"])
            name = tg_name(user.display_name or user.first_name if user else "بازیکن")
            msg = await message.bot.send_message(
                chat_id,
                f"⏩ نوبت صحبت {name}\n\n⏱ {_format_duration(_turn_duration_local(game, str(result.get('kind', 'main'))))} فرصت صحبت داری",
                reply_markup=__import__("app.handlers.keyboards", fromlist=["day_turn_keyboard"]).day_turn_keyboard(
                    game.game_key, True, game.challenge_enabled, game.turn_color_enabled,
                    game.turn_color, game.challenge_color, True, result["kind"] not in {"extra", "challenge"}
                ),
            )
            from app.handlers.gameplay import _schedule_auto_next
            await _schedule_auto_next(message.bot, game.game_key, chat_id, msg.message_id)
    await message.answer("⏩ نکست انجام شد.")

@router.message(_exact("دستورات", "دستورها"))
async def text_commands(message: Message, state: FSMContext) -> None:
    if await state.get_state():
        return
    await message.answer(
        "📚 دستورات متنی\n\n"
        "پیوی: پروفایل، نقش من، رتبه\n"
        "گروه: لابی، جایگزین، انتخاب سردست، تنظیمات بازی، شروع دور، لغو بازی\n\n"
        "دستور فقط وقتی اجرا می‌شود که متن پیام دقیقاً برابر خود دستور باشد؛ "
        "مثلاً «جایگزین میخوایم» هیچ دستوری را اجرا نمی‌کند."
    )
