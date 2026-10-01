from aiogram import Router
from aiogram.types import CallbackQuery
from sqlalchemy import select
import json
import asyncio
from datetime import datetime, timezone

from app.db.models import Game, Group, User, Scenario, GameEvent
from app.db.session import session_factory
from app.repositories.games import GameRepository
from app.services.gameplay import (
    alive_players,
    all_players,
    current_round,
    resolve_night,
    start_match,
    choose_leader,
    start_round,
    start_voting,
    submit_night_action,
    submit_vote,
    resolve_challenge,
    start_day_turns,
    request_challenge,
    pending_challenge_requests,
    attach_challenge_request_message,
    choose_challenge,
    select_challenge_placement,
    auto_place_challenge_after,
    current_turn,
    next_turn,
    send_game_result_notifications,
)
from app.utils.text import tg_name

from app.handlers.keyboards import (
    day_keyboard,
    night_action_keyboard,
    vote_keyboard,
    day_turn_keyboard,
    challenge_requests_keyboard,
    challenge_placement_keyboard,
    continue_night_keyboard,
)

router = Router(name="gameplay")


def _day_keyboard(game, current: bool = False):
    try:
        emoji_settings = json.loads(game.emoji_settings or "{}")
    except (TypeError, ValueError):
        emoji_settings = {}
    return day_turn_keyboard(
        game.game_key,
        current,
        getattr(game, "challenge_enabled", True),
        getattr(game, "turn_color_enabled", True),
        getattr(game, "turn_color", "پیش‌فرض"),
        getattr(game, "challenge_color", "پیش‌فرض"),
        bool(emoji_settings.get("challenge", True)),
    )

_challenge_tasks = {}
_turn_tasks = {}
TURN_UPDATE_SECONDS = 10

def _turn_duration(game, kind: str) -> int:
    if kind == "challenge":
        return int(getattr(game, "challenge_seconds", 60) or 60)
    if kind == "extra":
        return int(getattr(game, "extra_challenge_seconds", 60) or 60)
    return int(getattr(game, "turn_seconds", 120) or 120)


def _duration_text(seconds: int) -> str:
    minutes, remainder = divmod(max(0, int(seconds)), 60)
    return f"{minutes:02d}:{remainder:02d}"


async def _load(session, key):
    return await GameRepository.get_by_key(session, key)

async def _schedule_auto_next(bot, game_key: str, chat_id: int | None = None, message_id: int | None = None):
    async def runner():
        while True:
            await asyncio.sleep(TURN_UPDATE_SECONDS)
            async with session_factory() as session:
                game = await _load(session, game_key)
                if not game or game.status != "running":
                    return
                turn = await current_turn(session, game.id)
                if not turn or turn.get("status") != "active":
                    return
                started_at = turn.get("started_at")
                if not started_at:
                    return
                try:
                    started = datetime.fromisoformat(started_at)
                except (TypeError, ValueError):
                    return
                if started.tzinfo is None:
                    started = started.replace(tzinfo=timezone.utc)
                elapsed = max(0, int((datetime.now(timezone.utc) - started).total_seconds()))
                remaining = max(0, _turn_duration(game, str(turn.get("kind", "main"))) - elapsed)
                if chat_id and message_id:
                    user = await session.get(User, int(turn["user_id"]))
                    name = tg_name(user.display_name or user.first_name if user else "بازیکن")
                    minutes, seconds = divmod(remaining, 60)
                    try:
                        await bot.edit_message_text(
                            f"🗣 نوبت صحبت {name}\n\n⏱ {minutes:02d}:{seconds:02d} فرصت صحبت داری",
                            chat_id=chat_id,
                            message_id=message_id,
                            reply_markup=_day_keyboard(game, True),
                        )
                    except Exception:
                        pass
                if remaining > 0:
                    continue
                if not game.next_auto_enabled:
                    return
                try:
                    result = await next_turn(session, game)
                except ValueError:
                    return
                if not chat_id:
                    return
                if result["kind"] == "finished_day":
                    await bot.send_message(
                        chat_id,
                        "زمان نوبت به پایان رسید و صحبت‌های این دور تمام شد.",
                        reply_markup=day_keyboard(game.game_key, await alive_players(session, game.id)),
                    )
                    return
                user = await session.get(User, result["user_id"])
                name = tg_name(user.display_name or user.first_name if user else "بازیکن")
                msg = await bot.send_message(
                    chat_id,
                    f"🗣 نوبت صحبت {name}\n\n⏱ {_duration_text(_turn_duration(game, str(turn.get('kind', 'main'))))} فرصت صحبت داری",
                    reply_markup=_day_keyboard(game, True),
                )
                _turn_tasks[game.game_key] = asyncio.create_task(
                    _schedule_auto_next(bot, game_key, chat_id, msg.message_id)
                )
                return
    old = _turn_tasks.get(game_key)
    if old and old is not asyncio.current_task():
        old.cancel()
    task = asyncio.create_task(runner())
    _turn_tasks[game_key] = task

def _leader_selection_keyboard(game_key: str, assignments):
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    rows = [[InlineKeyboardButton(text="🎲 انتخاب خودکار سردست", callback_data=f"leader:auto:{game_key}")]]
    for player, _role, user in assignments:
        rows.append([InlineKeyboardButton(
            text=f"👤 {player.seat:02d} - {tg_name(user.display_name or user.first_name or 'بازیکن')}",
            callback_data=f"leader:select:{game_key}:{user.id}",
        )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _group_chat_id(session, game):
    group = await session.get(Group, game.group_id)
    return group.telegram_id if group else None


async def _public_status_roster(session, game) -> str:
    try:
        emoji_settings = json.loads(game.emoji_settings or "{}")
    except (TypeError, ValueError):
        emoji_settings = {}
    rows = await all_players(session, game.id)
    lines = ["👥 لیست بازیکنان حاضر در بازی", ""]
    for player, user, _role in rows:
        if player.is_reserved:
            continue
        name = tg_name(user.display_name or user.first_name or user.username or "بازیکن")
        marks = []
        if player.alive:
            if player.silence_until_round is not None and emoji_settings.get("silence", True):
                marks.append("🔇")
            if player.extra_turn_round is not None and emoji_settings.get("extra_turn", True):
                marks.append("➕")
            if player.warning_count and emoji_settings.get("warning", True):
                marks.append(f"⚠️{player.warning_count}")
            state = "زنده"
        else:
            if player.exit_type == "death" and emoji_settings.get("death", True):
                marks.append("💀")
            elif player.exit_type == "kick" and emoji_settings.get("kick", True):
                marks.append("⛔")
            elif player.exit_type == "slaughter" and emoji_settings.get("slaughter", True):
                marks.append("🩸")
            # Face-off is a hidden act and is never exposed in the public roster.
            state = "حذف‌شده"
        lines.append(f"{player.seat:02d}. {' '.join(marks)} {name} — {state}".strip())
    return "\n".join(lines)

async def update_round_roster(bot, session, game, chat_id: int | None = None) -> None:
    """Maintain one roster message per round; update it instead of sending new rosters."""
    round_no = await current_round(session, game.id)
    result = await session.execute(select(GameEvent).where(
        GameEvent.game_id == game.id, GameEvent.event_type == "round_roster_message"
    ).order_by(GameEvent.id.desc()))
    event = None
    for candidate in result.scalars():
        data = json.loads(candidate.payload or "{}")
        if int(data.get("round_no", -1)) == int(round_no):
            event = candidate
            break
    data = json.loads(event.payload or "{}") if event else {}
    target_chat = chat_id or data.get("chat_id") or await _group_chat_id(session, game)
    if not target_chat:
        return
    roster_text = await _public_status_roster(session, game)
    if event and data.get("message_id"):
        try:
            await bot.edit_message_text(roster_text, chat_id=int(target_chat), message_id=int(data["message_id"]))
            return
        except Exception:
            pass
    try:
        msg = await bot.send_message(int(target_chat), roster_text)
    except Exception:
        return
    payload = {"round_no": int(round_no), "chat_id": int(target_chat), "message_id": msg.message_id}
    if event:
        event.payload = json.dumps(payload, ensure_ascii=False)
    else:
        session.add(GameEvent(game_id=game.id, event_type="round_roster_message",
                              payload=json.dumps(payload, ensure_ascii=False)))
    await session.commit()

async def _send_night_menus(bot, session, game):
    if not game.auto_play:
        return
    players = await alive_players(session, game.id)
    for player, user, role in players:
        if not role or role.key not in {"godfather", "mafia", "doctor", "detective"}:
            continue
        action = "mafia_kill" if role.team == "mafia" else f"{role.key}_{'save' if role.key == 'doctor' else 'check'}"
        try:
            await bot.send_message(
                user.telegram_id,
                f"🌙 اقدام شب\n\nنقش: {role.name_fa}\nاقدام خود را انتخاب کن:",
                reply_markup=night_action_keyboard(game.game_key, action, players, user.id),
            )
        except Exception:
            pass

@router.callback_query(lambda c: c.data and c.data.startswith("game:start:"))
async def start_match_handler(callback: CallbackQuery):
    key = callback.data.split(":", 2)[2]
    if not callback.from_user or not callback.message:
        return
    async with session_factory() as session:
        game = await _load(session, key)
        if not game or game.status != "waiting":
            await callback.answer("بازی قابل شروع نیست.", show_alert=True)
            return
        host = await session.get(User, game.host_user_id)
        if not host or host.telegram_id != callback.from_user.id:
            await callback.answer("فقط سازنده بازی می‌تواند شروع کند.", show_alert=True)
            return
        players = await GameRepository.players(session, game.id)
        scenario = await session.get(Scenario, game.scenario_id)
        if not scenario or len(players) < scenario.min_players:
            await callback.answer("تعداد بازیکنان کافی نیست.", show_alert=True)
            return
        try:
            assignments = await start_match(session, game)
        except ValueError as exc:
            await callback.answer(str(exc), show_alert=True)
            return
        await callback.message.edit_text(
            f"بازی آماده شد.\nسناریو: {scenario.name_fa}\nبازیکنان: {len(assignments)}\n\n"
            "نقش‌ها خصوصی ارسال شدند.\n"
            "اکنون سردست باید انتخاب شود؛ انتخاب می‌تواند دستی یا خودکار باشد.",
            reply_markup=_leader_selection_keyboard(game.game_key, assignments),
        )
        for _, role, user in assignments:
            try:
                await callback.bot.send_message(
                    user.telegram_id,
                    f"نقش شما\n\nنقش: {role.name_fa}\nتیم: {role.team}\n\n{role.description}",
                )
            except Exception:
                pass
        await callback.answer("نقش‌ها پخش شد؛ مرحله انتخاب سردست آغاز شد.")


@router.callback_query(lambda c: c.data and c.data.startswith("night:"))
async def night_callback(callback: CallbackQuery):
    parts = callback.data.split(":")
    if not callback.from_user:
        return
    if len(parts) == 3 and parts[0] == "night" and parts[1] == "resolve":
        _, _, key = parts
        action = "resolve"
        target = None
    elif len(parts) == 4 and parts[0] == "night":
        _, action, key, target = parts
    else:
        await callback.answer("درخواست شب نامعتبر است.", show_alert=True)
        return
    async with session_factory() as session:
        game = await _load(session, key)
        if not game:
            await callback.answer("بازی پیدا نشد.", show_alert=True)
            return
        if action == "resolve":
            try:
                result = await resolve_night(session, game)
            except ValueError as exc:
                await callback.answer(str(exc), show_alert=True)
                return
            chat_id = await _group_chat_id(session, game)
            if not result["winner"]:
                await update_round_roster(callback.bot, session, game, chat_id)
            if result["winner"]:
                await send_game_result_notifications(callback.bot, session, game)
                text = f"بازی تمام شد. تیم {('مافیا' if result['winner']=='mafia' else 'شهروند')} برنده شد."
            elif result["eliminated"]:
                text = "روز آغاز شد."
            else:
                text = "روز آغاز شد.\nاین شب حذف نداشت."
            if chat_id:
                if not result["winner"]:
                    await start_day_turns(session, game)
                    turn = await current_turn(session, game.id)
                    speaker = await session.get(User, int(turn["user_id"])) if turn else None
                    name = speaker.display_name or speaker.first_name if speaker else "بازیکن"
                    msg = await callback.bot.send_message(
                        chat_id,
                        f"{text}\n\n{await _public_status_roster(session, game)}\n\n🗣 نوبت صحبت {name}\n\n⏱ {int(game.turn_seconds or 120) // 60:02d}:{int(game.turn_seconds or 120) % 60:02d} فرصت صحبت داری",
                        reply_markup=_day_keyboard(game, True),
                    )
                    await _schedule_auto_next(callback.bot, game.game_key, chat_id, msg.message_id)
                else:
                    await callback.bot.send_message(chat_id, text)
            await callback.answer("شب بررسی شد.")
            return
        actor = (await session.execute(select(User).where(User.telegram_id == callback.from_user.id))).scalar_one_or_none()
        if not actor:
            await callback.answer("کاربر بازی پیدا نشد.", show_alert=True)
            return
        try:
            result = await submit_night_action(session, game, actor, action, int(target))
        except (ValueError, TypeError) as exc:
            await callback.answer(str(exc), show_alert=True)
            return
        if result["detective_result"]:
            await callback.bot.send_message(actor.telegram_id, f"نتیجه کارآگاهی: هدف شما {result['detective_result']} است.")
        if result["resolved"]:
            resolved = await resolve_night(session, game)
            chat_id = await _group_chat_id(session, game)
            if not resolved["winner"]:
                await update_round_roster(callback.bot, session, game, chat_id)
            if resolved["winner"]:
                text = f"بازی تمام شد. تیم {('مافیا' if resolved['winner']=='mafia' else 'شهروند')} برنده شد."
            elif resolved["eliminated"]:
                text = f"روز آغاز شد. بازیکن {resolved['eliminated'].display_name} در شب حذف شد."
            else:
                text = "روز آغاز شد. این شب حذف نداشت."
            if chat_id:
                if not resolved["winner"]:
                    await start_day_turns(session, game)
                    turn = await current_turn(session, game.id)
                    speaker = await session.get(User, int(turn["user_id"])) if turn else None
                    name = speaker.display_name or speaker.first_name if speaker else "بازیکن"
                    msg = await callback.bot.send_message(
                        chat_id,
                        f"{text}\n\n{await _public_status_roster(session, game)}\n\n🗣 نوبت صحبت {name}\n\n⏱ {_duration_text(_turn_duration(game, str(turn.get('kind', 'main'))))} فرصت صحبت داری",
                        reply_markup=_day_keyboard(game, True),
                    )
                    await _schedule_auto_next(callback.bot, game.game_key, chat_id, msg.message_id)
                else:
                    await callback.bot.send_message(chat_id, text)
        await callback.answer("اقدام شب ثبت شد.")

@router.callback_query(lambda c: c.data and c.data.startswith("turn:request_challenge:"))
async def turn_request_challenge_handler(callback: CallbackQuery):
    key = callback.data.split(":", 2)[2]
    if not callback.from_user:
        return
    async with session_factory() as session:
        game = await _load(session, key)
        actor = (await session.execute(select(User).where(User.telegram_id == callback.from_user.id))).scalar_one_or_none()
        if not game or not actor:
            await callback.answer("بازی یا کاربر پیدا نشد.", show_alert=True)
            return
        try:
            result = await request_challenge(session, game, actor)
        except ValueError as exc:
            await callback.answer(str(exc), show_alert=True)
            return
        turn_owner = await session.get(User, result["turn_user_id"])
        if not turn_owner or not callback.message:
            await callback.answer("صاحب نوبت یا پیام بازی پیدا نشد.", show_alert=True)
            return
        event = await session.get(GameEvent, result["event_id"])
        request_data = json.loads(event.payload or "{}")
        request_data["requester_name"] = actor.display_name or actor.first_name
        request_data["chat_id"] = callback.message.chat.id
        request_data["message_id"] = None
        event.payload = json.dumps(request_data, ensure_ascii=False)
        await session.commit()
        msg = await callback.bot.send_message(
            callback.message.chat.id,
            f"درخواست چالش: {tg_name(actor.display_name or actor.first_name)}\n"
            f"صاحب ترن اصلی: {tg_name(turn_owner.display_name or turn_owner.first_name)}\n\n"
            "صاحب ترن یکی از درخواست‌ها را انتخاب می‌کند.",
            reply_markup=challenge_requests_keyboard(game.game_key, [(event, request_data)]),
        )
        await attach_challenge_request_message(session, event.id, callback.message.chat.id, msg.message_id)
        await callback.answer("درخواست چالش در گروه ثبت شد.")

@router.callback_query(lambda c: c.data and c.data.startswith("challenge:grant:"))
async def challenge_grant_handler(callback: CallbackQuery):
    parts = callback.data.split(":")
    if len(parts) != 4 or not callback.from_user:
        return
    _, _, key, event_id = parts
    async with session_factory() as session:
        game = await _load(session, key)
        actor = (await session.execute(select(User).where(User.telegram_id == callback.from_user.id))).scalar_one_or_none()
        if not game or not actor:
            await callback.answer("بازی یا کاربر پیدا نشد.", show_alert=True)
            return
        try:
            result = await choose_challenge(session, game, actor, int(event_id))
        except ValueError as exc:
            await callback.answer(str(exc), show_alert=True)
            return
        for req_event, req_data in result["requests"]:
            chat_id = req_data.get("chat_id")
            message_id = req_data.get("message_id")
            requester = await session.get(User, int(req_data["requester_id"]))
            name = requester.display_name or requester.first_name if requester else "بازیکن"
            if chat_id and message_id:
                try:
                    if req_event.id == result["request_event_id"]:
                        await callback.bot.edit_message_text(
                            f"🤏🏼 چالش برای {name} تأیید شد.\n\nزمان اجرای چالش را انتخاب کنید:",
                            chat_id=chat_id,
                            message_id=message_id,
                            reply_markup=challenge_placement_keyboard(game.game_key, req_event.id),
                        )
                    else:
                        await callback.bot.edit_message_text(
                            f"درخواست چالش {name} رد شد؛ چالش به بازیکن دیگری داده شد.",
                            chat_id=chat_id,
                            message_id=message_id,
                        )
                except Exception:
                    pass
        await callback.answer("چالش داده شد.")
        async def auto_after():
            await asyncio.sleep(20)
            async with session_factory() as timer_session:
                timer_game = await _load(timer_session, key)
                if not timer_game:
                    return
                try:
                    placed = await auto_place_challenge_after(timer_session, timer_game, result["request_event_id"])
                except ValueError:
                    return
                if placed:
                    chat_id = await _group_chat_id(timer_session, timer_game)
                    req = await timer_session.get(User, result["requester_id"])
                    if chat_id and req:
                        await callback.bot.send_message(
                            chat_id,
                            f"زمان انتخاب نشد؛ چالش {tg_name(req.display_name or req.first_name)} بعد از صحبت اجرا می‌شود.",
                        )
        task = asyncio.create_task(auto_after())
        _challenge_tasks[result["request_event_id"]] = task


@router.callback_query(lambda c: c.data and c.data.startswith("challenge:place:"))
async def challenge_place_handler(callback: CallbackQuery):
    parts = callback.data.split(":")
    if len(parts) != 5 or not callback.from_user:
        return
    _, _, key, event_id, placement = parts
    async with session_factory() as session:
        game = await _load(session, key)
        actor = (await session.execute(select(User).where(User.telegram_id == callback.from_user.id))).scalar_one_or_none()
        if not game or not actor:
            await callback.answer("بازی یا کاربر پیدا نشد.", show_alert=True)
            return
        try:
            result = await select_challenge_placement(session, game, actor, int(event_id), placement)
        except ValueError as exc:
            await callback.answer(str(exc), show_alert=True)
            return
        task = _challenge_tasks.pop(int(event_id), None)
        if task:
            task.cancel()
        turn_task = _turn_tasks.pop(game.id, None)
        if turn_task:
            turn_task.cancel()
        requester = await session.get(User, result["requester_id"])
        name = requester.display_name or requester.first_name if requester else "بازیکن"
        chat_id = await _group_chat_id(session, game)
        await callback.message.edit_text(
            f"⚔️ چالش برای {name} تأیید شد.\nزمان اجرا: {'قبل از صحبت' if result['placement'] == 'before' else 'بعد از صحبت'}"
        )
        if chat_id:
            if result["placement"] == "before":
                msg = await callback.bot.send_message(
                    chat_id,
                    f"⚔️ چالش برای {name} اجرا شد.\n\n⏱ {_duration_text(_turn_duration(game, 'challenge'))} فرصت صحبت داری",
                    reply_markup=day_turn_keyboard(
                        game.game_key, True, game.challenge_enabled,
                        game.turn_color_enabled, game.turn_color, game.challenge_color,
                        True, False
                    ),
                )
                await _schedule_auto_next(callback.bot, game.game_key, chat_id, msg.message_id)
            else:
                await callback.bot.send_message(chat_id, f"چالش {name} بعد از پایان این نوبت اجرا می‌شود.")
        await callback.answer("زمان چالش ثبت شد.")


async def _reschedule_auto_next(bot, game):
    if game.next_auto_enabled and game.status == "running":
        await _schedule_auto_next(bot, game.game_key)


@router.callback_query(lambda c: c.data and c.data.startswith("turn:next:"))
async def next_turn_handler(callback: CallbackQuery):
    key = callback.data.split(":", 2)[2]
    if not callback.from_user:
        return
    async with session_factory() as session:
        game = await _load(session, key)
        actor = (await session.execute(select(User).where(User.telegram_id == callback.from_user.id))).scalar_one_or_none()
        if not game or not actor:
            await callback.answer("بازی یا کاربر پیدا نشد.", show_alert=True)
            return
        turn = await current_turn(session, game.id)
        if not turn:
            await callback.answer("نوبت فعالی وجود ندارد.", show_alert=True)
            return
        host = await session.get(User, game.host_user_id) if game.host_user_id else None
        is_host = bool(host and host.id == actor.id)
        is_turn_owner = int(turn.get("user_id", -1)) == actor.id
        if is_host and not game.next_host_enabled:
            await callback.answer("نکست گرداننده در تنظیمات بازی غیرفعال است.", show_alert=True)
            return
        if not is_host and is_turn_owner and not game.next_player_enabled:
            await callback.answer("نکست بازیکن در تنظیمات بازی غیرفعال است.", show_alert=True)
            return
        if not is_host and not is_turn_owner:
            await callback.answer("فقط گرداننده یا صاحب نوبت فعلی می‌تواند نکست بزند.", show_alert=True)
            return
        try:
            result = await next_turn(session, game)
        except ValueError as exc:
            await callback.answer(str(exc), show_alert=True)
            return
        chat_id = await _group_chat_id(session, game)
        if not chat_id:
            await callback.answer("گروه بازی پیدا نشد.", show_alert=True)
            return
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        if result["kind"] == "finished_day":
            old_task = _turn_tasks.pop(game.game_key, None)
            if old_task:
                old_task.cancel()

            await callback.bot.send_message(
                chat_id,
                "نوبت‌های اصلی این دور تمام شد. اکنون رأی‌گیری را می‌توانید شروع کنید.",
                reply_markup=day_keyboard(game.game_key, await alive_players(session, game.id)),
            )
        else:
            user = await session.get(User, result["user_id"])
            name = tg_name(user.display_name or user.first_name if user else "بازیکن")
            kind = "چالش" if result["kind"] == "challenge" else ("ترن اضافه" if result["kind"] == "extra" else "اصلی")
            msg = await callback.bot.send_message(
                chat_id,
                f"🗣 نوبت صحبت {name}\n\n⏱ {_duration_text(_turn_duration(game, str(result.get('kind', 'main'))))} فرصت صحبت داری",
                reply_markup=day_turn_keyboard(
                    game.game_key, True, game.challenge_enabled,
                    game.turn_color_enabled, game.turn_color, game.challenge_color,
                    True, result["kind"] not in {"extra", "challenge"}
                ),
            )
            await _schedule_auto_next(callback.bot, game.game_key, chat_id, msg.message_id)
        await callback.answer("نکست ترن انجام شد.")


@router.callback_query(lambda c: c.data and c.data.startswith("day:night:"))
async def day_night_handler(callback: CallbackQuery):
    key = callback.data.split(":", 2)[2]
    if not callback.from_user:
        return
    async with session_factory() as session:
        game = await _load(session, key)
        actor = (await session.execute(select(User).where(User.telegram_id == callback.from_user.id))).scalar_one_or_none()
        if not game or not actor:
            await callback.answer("بازی یا کاربر پیدا نشد.", show_alert=True)
            return
        host = await session.get(User, game.host_user_id) if game.host_user_id else None
        if not host or host.id != actor.id:
            await callback.answer("فقط گرداننده می‌تواند فاز شب را شروع کند.", show_alert=True)
            return
        turn = await current_turn(session, game.id)
        if not turn or turn.get("status") != "finished":
            await callback.answer("ابتدا باید صحبت‌های دور تمام شود.", show_alert=True)
            return
        if game.phase != "day":
            await callback.answer("مرحله روز فعال نیست.", show_alert=True)
            return
        game.phase = "night"
        await session.commit()
        chat_id = await _group_chat_id(session, game)
        if chat_id:
            await callback.bot.send_message(
                chat_id,
                "🌙 فاز شب آغاز شد.",
                reply_markup=continue_night_keyboard(game.game_key),
            )
            await _send_night_menus(callback.bot, session, game)
        await callback.answer("فاز شب آغاز شد.")

@router.callback_query(lambda c: c.data and c.data.startswith("day:finish:"))
async def day_finish_handler(callback: CallbackQuery):
    key = callback.data.split(":", 2)[2]
    if not callback.from_user:
        return
    async with session_factory() as session:
        game = await _load(session, key)
        actor = (await session.execute(select(User).where(User.telegram_id == callback.from_user.id))).scalar_one_or_none()
        if not game or not actor:
            await callback.answer("بازی یا کاربر پیدا نشد.", show_alert=True)
            return
        host = await session.get(User, game.host_user_id) if game.host_user_id else None
        if not host or host.id != actor.id:
            await callback.answer("فقط گرداننده می‌تواند بازی را تمام کند.", show_alert=True)
            return
        turn = await current_turn(session, game.id)
        if not turn or turn.get("status") != "finished":
            await callback.answer("تا پایان نوبت‌های این دور امکان اتمام بازی نیست.", show_alert=True)
            return
        await __import__("app.services.gameplay", fromlist=["finalize_game"]).finalize_game(session, game, "draw")
        await session.commit()
        await send_game_result_notifications(callback.bot, session, game)
        await callback.message.edit_text("🏁 بازی توسط گرداننده به پایان رسید. نتیجه: بدون برنده.")
        await callback.answer("بازی تمام شد.")

@router.callback_query(lambda c: c.data and c.data.startswith("day:vote:"))
async def day_vote_handler(callback: CallbackQuery):
    key = callback.data.split(":", 2)[2]
    if not callback.from_user:
        return
    async with session_factory() as session:
        game = await _load(session, key)
        actor = (await session.execute(select(User).where(User.telegram_id == callback.from_user.id))).scalar_one_or_none()
        if not game or not actor:
            await callback.answer("بازی پیدا نشد.", show_alert=True)
            return
        host = await session.get(User, game.host_user_id) if game.host_user_id else None
        if not host or host.id != actor.id:
            await callback.answer("فقط گرداننده می‌تواند رأی‌گیری را شروع کند.", show_alert=True)
            return
        try:
            await start_voting(session, game)
        except ValueError as exc:
            await callback.answer(str(exc), show_alert=True)
            return
        players = await alive_players(session, game.id)
        await callback.message.edit_text(
            f"🗳 رأی‌گیری دور {await current_round(session, game.id)}\n\nهر بازیکن زنده یک رأی دارد. هدف را انتخاب کنید:",
            reply_markup=vote_keyboard(game.game_key, players),
        )
        await callback.answer("رأی‌گیری شروع شد.")


@router.callback_query(lambda c: c.data and c.data.startswith("vote:"))
async def vote_handler(callback: CallbackQuery):
    parts = callback.data.split(":")
    if len(parts) != 3 or not callback.from_user:
        return
    key, target_id = parts[1], int(parts[2])
    async with session_factory() as session:
        game = await _load(session, key)
        actor = (await session.execute(select(User).where(User.telegram_id == callback.from_user.id))).scalar_one_or_none()
        if not game or not actor:
            await callback.answer("بازی یا کاربر پیدا نشد.", show_alert=True)
            return
        try:
            result = await submit_vote(session, game, actor, target_id)
        except (ValueError, TypeError) as exc:
            await callback.answer(str(exc), show_alert=True)
            return
        if not result["resolved"]:
            await callback.answer("رأی شما ثبت شد.")
            return

        if result["winner"]:
            await send_game_result_notifications(callback.bot, session, game)
            winner_label = {
                "mafia": "مافیا",
                "citizen": "شهروند",
                "independent": "مستقل",
                "citizen_independent": "شهروند و مستقل",
                "draw": "مساوی",
            }.get(result["winner"], result["winner"])
            await callback.message.edit_text(
                f"🏁 بازی تمام شد.\n\nبرنده: {winner_label}\n\n"
                "آمار و نتیجه نهایی ثبت شد."
            )
        else:
            if result["eliminated"]:
                name = tg_name(result["eliminated"].display_name or result["eliminated"].first_name)
                text = f"🗳 رأی‌گیری تمام شد.\n\nبازیکن {name} حذف شد."
            else:
                text = "🗳 رأی‌گیری تمام شد.\n\nرأی‌گیری مساوی شد و کسی حذف نشد."
            await update_round_roster(callback.bot, session, game, callback.message.chat.id)
            text += "\n\n🌙 شب بعد آغاز شد."
            await callback.message.edit_text(text)
            if game.auto_play:
                await _send_night_menus(callback.bot, session, game)
            else:
                host = await session.get(User, game.host_user_id) if game.host_user_id else None
                if host:
                    await callback.bot.send_message(
                        callback.message.chat.id,
                        "🌙 فاز شب آغاز شد. اقدامات شب در PV بازیکنان فعال است و گرداننده می‌تواند حل شب را اجرا کند.",
                        reply_markup=continue_night_keyboard(game.game_key),
                    )
        await callback.answer("رأی ثبت شد.")
