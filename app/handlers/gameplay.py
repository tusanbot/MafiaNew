from aiogram import Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, ChatPermissions
from sqlalchemy import select
import json
import asyncio
from datetime import datetime, timezone

from app.db.models import Game, Group, GroupSettings, User, Scenario, GameEvent
from app.db.session import session_factory
from app.repositories.games import GameRepository
from app.services.gameplay import (
    alive_players,
    all_players,
    current_round,
    resolve_night,
    night_ready,
    start_match,
    choose_leader,
    start_round,
    start_voting,
    submit_night_action,
    resolve_challenge,
    start_day_turns,
    start_new_day_round,
    vote1_start, vote1_current_target, cast_vote_phase, finish_vote1_target, advance_vote1,
    toggle_vote2_candidate, start_vote2, advance_defense_turn, finish_vote2, advance_vote2,
    _latest_vote_state, _vote_records_for_target, _vote_records_for_phase, _revoked_vote_ids, _event,
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
from app.utils.text import tg_name, tg_mention

from app.handlers.keyboards import (
    day_keyboard,
    night_action_keyboard,
    vote_keyboard,
    day_turn_keyboard,
    challenge_requests_keyboard,
    challenge_placement_keyboard,
    continue_night_keyboard,
    finish_game_keyboard,
    voting_setup_keyboard, voting_delay_keyboard, voting_duration_keyboard, voting_mode_keyboard,
    vote_rights_keyboard, vote_right_confirm_keyboard, vote1_target_keyboard, vote1_complete_keyboard,
    defense_selection_keyboard, vote2_target_keyboard, vote2_ballot_keyboard, vote2_private_voters_keyboard, vote2_private_targets_keyboard, vote2_complete_keyboard,
    vote2_setup_keyboard, vote2_result_keyboard,
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
_turn_live_tasks = {}
TURN_UPDATE_SECONDS = 10
TURN_LIVE_UPDATE_SECONDS = 10

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

async def _register_turn_message(session, game, *, chat_id: int, message_id: int, turn: dict) -> None:
    """Persist the public message belonging to this exact turn."""
    payload = {
        "round_no": int(turn.get("round_no", 0)),
        "user_id": int(turn.get("user_id")),
        "kind": str(turn.get("kind", "main")),
        "chat_id": int(chat_id),
        "message_id": int(message_id),
        "status": "active",
    }
    session.add(
        GameEvent(
            game_id=game.id,
            event_type="turn_message",
            payload=json.dumps(payload, ensure_ascii=False),
        )
    )
    await session.commit()


async def _turn_message(session, game, turn: dict | None = None):
    """Find the public message for the current turn."""
    turn = turn or await current_turn(session, game.id)
    if not turn:
        return None, None
    result = await session.execute(
        select(GameEvent)
        .where(GameEvent.game_id == game.id, GameEvent.event_type == "turn_message")
        .order_by(GameEvent.id.desc())
    )
    for event in result.scalars():
        data = json.loads(event.payload or "{}")
        if (
            data.get("status") == "active"
            and int(data.get("round_no", -1)) == int(turn.get("round_no", -2))
            and int(data.get("user_id", -1)) == int(turn.get("user_id", -2))
            and data.get("kind") == str(turn.get("kind", "main"))
        ):
            return event, data
    return None, None


async def _finish_turn_message(bot, session, game, turn: dict | None = None) -> None:
    """Finalize the exact turn message and stop its live countdown."""
    event, data = await _turn_message(session, game, turn)
    if not event or not data:
        return
    if turn:
        task = _turn_live_tasks.pop(game.game_key, None)
        if task and task is not asyncio.current_task():
            task.cancel()
    try:
        user = await session.get(User, int(turn.get("user_id"))) if turn else None
        name = tg_name(user.display_name or user.first_name if user else "بازیکن")
        await bot.edit_message_text(
            f"🗣 نوبت {name} تموم شد",
            chat_id=int(data["chat_id"]),
            message_id=int(data["message_id"]),
            reply_markup=None,
            parse_mode="HTML",
        )
    except Exception:
        pass
    data["status"] = "finished"
    event.payload = json.dumps(data, ensure_ascii=False)
    await session.commit()


async def _delete_turn_challenge_messages(bot, session, game, turn: dict | None = None) -> None:
    """Delete every challenge-request message belonging to the finished turn."""
    turn = turn or await current_turn(session, game.id)
    if not turn:
        return
    round_no = int(turn.get("round_no", 0))
    turn_user_id = int(turn.get("user_id", -1))
    result = await session.execute(
        select(GameEvent)
        .where(GameEvent.game_id == game.id, GameEvent.event_type == "challenge_request")
        .order_by(GameEvent.id.asc())
    )
    changed = False
    for event in result.scalars():
        data = json.loads(event.payload or "{}")
        if (
            int(data.get("round_no", -1)) != round_no
            or int(data.get("target_turn_user_id", -1)) != turn_user_id
        ):
            continue
        chat_id = data.get("chat_id")
        message_id = data.get("message_id")
        if chat_id and message_id:
            try:
                await bot.delete_message(chat_id=int(chat_id), message_id=int(message_id))
            except Exception:
                pass
        if data.get("status") not in {"finished", "deleted"}:
            data["status"] = "deleted"
            event.payload = json.dumps(data, ensure_ascii=False)
            changed = True
    if changed:
        await session.commit()


async def _send_turn_message(bot, session, game, chat_id: int, turn: dict | None = None):
    turn = turn or await current_turn(session, game.id)
    if not turn:
        return None
    user = await session.get(User, int(turn["user_id"]))
    raw_name = user.display_name or user.first_name if user else "بازیکن"
    kind = str(turn.get("kind", "main"))
    requests = await pending_challenge_requests(session, game) if kind == "main" else []
    request_section = "\n\n<b>کسایی که درخواست چالش دارن:</b>" if requests else ""
    text = (f"🗣 نوبت صحبت {tg_mention(user.telegram_id, raw_name) if user else '<b>بازیکن</b>'}\n\n"
            f"⏱ {_duration_text(_turn_duration(game, kind))}{request_section}")
    msg = await bot.send_message(
        chat_id, text,
        reply_markup=day_turn_keyboard(game.game_key, True, game.challenge_enabled, game.turn_color_enabled,
                                       game.turn_color, game.challenge_color, True, kind not in {"extra", "challenge"} and not turn.get("challenge_consumed", False), requests),
        parse_mode="HTML",
    )
    await _register_turn_message(session, game, chat_id=chat_id, message_id=msg.message_id, turn=turn)
    await _schedule_turn_live(bot, game.game_key)
    return msg


def _turn_remaining(game, turn: dict) -> int:
    started_at = turn.get("started_at")
    if not started_at:
        return _turn_duration(game, str(turn.get("kind", "main")))
    try:
        started = datetime.fromisoformat(started_at)
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        elapsed = max(0, int((datetime.now(timezone.utc) - started).total_seconds()))
        return max(0, _turn_duration(game, str(turn.get("kind", "main"))) - elapsed)
    except (TypeError, ValueError):
        return _turn_duration(game, str(turn.get("kind", "main")))


async def _refresh_turn_message(bot, session, game, turn: dict | None = None) -> None:
    turn = turn or await current_turn(session, game.id)
    if not turn:
        return
    event, data = await _turn_message(session, game, turn)
    if not event or not data:
        return
    user = await session.get(User, int(turn["user_id"]))
    raw_name = user.display_name or user.first_name if user else "بازیکن"
    kind = str(turn.get("kind", "main"))
    requests = await pending_challenge_requests(session, game) if kind == "main" else []
    request_section = "\n\n<b>کسایی که درخواست چالش دارن:</b>" if requests else ""
    remaining = _turn_remaining(game, turn)
    text = f"🗣 نوبت صحبت {tg_mention(user.telegram_id, raw_name) if user else '<b>بازیکن</b>'}\n\n⏱ {_duration_text(remaining)}{request_section}"
    try:
        await bot.edit_message_text(text, chat_id=int(data["chat_id"]), message_id=int(data["message_id"]),
                                    reply_markup=day_turn_keyboard(game.game_key, True, game.challenge_enabled, game.turn_color_enabled,
                                                                   game.turn_color, game.challenge_color, True, kind not in {"extra", "challenge"} and not turn.get("challenge_consumed", False), requests),
                                    parse_mode="HTML")
    except Exception:
        pass


async def _turn_live_countdown(bot, game_key: str):
    try:
        last_text = None
        while True:
            await asyncio.sleep(TURN_LIVE_UPDATE_SECONDS)
            async with session_factory() as session:
                game = await _load(session, game_key)
                if not game or game.status != "running":
                    return
                turn = await current_turn(session, game.id)
                if not turn or turn.get("status") not in {"active", "paused"}:
                    return
                remaining = _turn_remaining(game, turn)
                event, data = await _turn_message(session, game, turn)
                if not event or not data:
                    return
                user = await session.get(User, int(turn["user_id"]))
                raw_name = user.display_name or user.first_name if user else "بازیکن"
                kind = str(turn.get("kind", "main"))
                requests = await pending_challenge_requests(session, game) if kind == "main" else []
                request_section = "\n\n<b>کسایی که درخواست چالش دارن:</b>" if requests else ""
                text = f"🗣 نوبت صحبت {tg_mention(user.telegram_id, raw_name) if user else '<b>بازیکن</b>'}\n\n⏱ {_duration_text(remaining)}{request_section}"
                if text == last_text:
                    continue
                last_text = text
                try:
                    await bot.edit_message_text(
                        text,
                        chat_id=int(data["chat_id"]),
                        message_id=int(data["message_id"]),
                        reply_markup=day_turn_keyboard(
                            game.game_key, True, game.challenge_enabled, game.turn_color_enabled,
                            game.turn_color, game.challenge_color, True,
                            kind not in {"extra", "challenge"} and not turn.get("challenge_consumed", False), requests
                        ),
                        parse_mode="HTML",
                    )
                except Exception:
                    pass
    except asyncio.CancelledError:
        return
    finally:
        current = _turn_live_tasks.get(game_key)
        if current is asyncio.current_task():
            _turn_live_tasks.pop(game_key, None)


async def _schedule_turn_live(bot, game_key: str):
    old = _turn_live_tasks.get(game_key)
    if old and old is not asyncio.current_task():
        old.cancel()
    _turn_live_tasks[game_key] = asyncio.create_task(_turn_live_countdown(bot, game_key))


async def _schedule_auto_next(bot, game_key: str, chat_id: int | None = None, message_id: int | None = None):
    async def runner():
        while True:
            await asyncio.sleep(TURN_UPDATE_SECONDS)
            async with session_factory() as session:
                game = await _load(session, game_key)
                if not game or game.status != "running":
                    return
                turn = await current_turn(session, game.id)
                if not turn or turn.get("status") not in ("active", "paused"):
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
                if remaining > 0:
                    continue
                if not game.next_auto_enabled:
                    return
                await _finish_turn_message(bot, session, game, turn)
                await _delete_turn_challenge_messages(bot, session, game, turn)
                try:
                    result = await next_turn(session, game)
                except ValueError:
                    return
                if not chat_id:
                    return
                if result["kind"] == "finished_day":
                    if message_id:
                        try:
                            if game.auto_play:
                                await start_voting(session, game)
                                await bot.send_message(
                                    chat_id,
                                    "🗳 رأی‌گیری دور شروع شد.",
                                    reply_markup=vote_keyboard(game.game_key, await alive_players(session, game.id)),
                                )
                            else:
                                await bot.send_message(
                                    chat_id,
                                    "🗳 نوبت‌های این دور تمام شد.",
                                    reply_markup=day_keyboard(game.game_key, await alive_players(session, game.id)),
                                )
                        except Exception:
                            pass
                    return
                new_turn = await current_turn(session, game.id)
                if new_turn:
                    await _send_turn_message(bot, session, game, chat_id, new_turn)
                return
    old = _turn_tasks.get(game_key)
    if old and old is not asyncio.current_task():
        old.cancel()
    task = asyncio.create_task(runner())
    _turn_tasks[game_key] = task

async def _group_chat_id(session, game):
    group = await session.get(Group, game.group_id)
    return group.telegram_id if group else None


async def _public_status_roster(session, game, *, include_state: bool = False, full_header: bool = False) -> str:
    try:
        emoji_settings = json.loads(game.emoji_settings or "{}")
    except (TypeError, ValueError):
        emoji_settings = {}
    rows = await all_players(session, game.id)
    challenge_ids = set()
    result = await session.execute(select(GameEvent).where(
        GameEvent.game_id == game.id, GameEvent.event_type == "challenge_request"
    ).order_by(GameEvent.id.desc()))
    for event in result.scalars():
        data = json.loads(event.payload or "{}")
        if data.get("status") == "accepted" and data.get("requester_id") is not None:
            challenge_ids.add(int(data["requester_id"]))
    scenario = await session.get(Scenario, game.scenario_id)
    host = await session.get(User, game.host_user_id) if game.host_user_id else None
    created = getattr(game, "created_at", None)
    if created and created.tzinfo:
        created = created.astimezone()
    date_text = created.strftime("%Y/%m/%d") if created else "—"
    if full_header:
        lines = ["\u200f༄", f"\u200f📓 <b>بازی شماره : {game.id}</b>", f"\u200f📆 تاریخ : {date_text}",
                 f"\u200f🗓 سناریو : {scenario.name_fa if scenario else 'نامشخص'}",
                 f"\u200f👮‍♂ گرداننده : {tg_mention(host.telegram_id, host.display_name or host.first_name) if host else 'نامشخص'}",
                 "", "◤◢◣◥◤◢◣◥◤◢◣◥", "👥 <b>لیست بازیکنان حاضر در بازی</b>"]
    else:
        lines = ["\u200f👥 <b>لیست بازیکنان</b>", ""]
    for player, user, _role in rows:
        if player.is_reserved:
            continue
        raw_name = user.display_name or user.first_name or user.username or "بازیکن"
        name = tg_mention(user.telegram_id, raw_name)
        marks = []
        if player.alive:
            if player.silence_until_round is not None and emoji_settings.get("silence", True): marks.append("🔇")
            if player.extra_turn_round is not None and emoji_settings.get("extra_turn", True): marks.append("➕")
            if player.warning_count and emoji_settings.get("warning", True): marks.append(f"⚠️{player.warning_count}")
        else:
            if player.exit_type == "death" and emoji_settings.get("death", True): marks.append("💀")
            elif player.exit_type == "kick" and emoji_settings.get("kick", True): marks.append("⛔")
            elif player.exit_type == "slaughter" and emoji_settings.get("slaughter", True): marks.append("🔪")
            elif player.exit_type == "vote": marks.append("🗳")
            elif player.exit_type == "faceoff": marks.append("🎭")
        if user.id in challenge_ids and emoji_settings.get("challenge", True): marks.append("🤏🏻")
        suffix = " — زنده" if include_state and player.alive else (" — حذف‌شده" if include_state else "")
        lines.append(f"\u200f{player.seat:02d}. {' '.join(marks)} {name}{suffix}".strip())
    if full_header: lines.append("◤◢◣◥◤◢◣◥◤◢◣◥")
    return "\n".join(lines)

async def _main_roster_event(session, game):
    result = await session.execute(select(GameEvent).where(
        GameEvent.game_id == game.id, GameEvent.event_type == "main_roster_message"
    ).order_by(GameEvent.id.desc()))
    return result.scalars().first()

async def update_main_roster(bot, session, game, chat_id: int | None = None) -> None:
    target_chat = chat_id or await _group_chat_id(session, game)
    if not target_chat: return
    event = await _main_roster_event(session, game)
    data = json.loads(event.payload or "{}") if event else {}
    message_id = data.get("message_id")
    text = await _public_status_roster(session, game, include_state=True, full_header=True)
    if message_id:
        try:
            await bot.edit_message_text(text, chat_id=int(target_chat), message_id=int(message_id), parse_mode="HTML")
            return
        except Exception:
            pass
    try:
        from app.handlers.keyboards import active_game_menu
        msg = await bot.send_message(
            int(target_chat),
            text,
            parse_mode="HTML",
            reply_markup=active_game_menu(game.group_id, "menu:active_game", game.game_key, False),
        )
    except Exception:
        return
    pinned = False
    try:
        await bot.pin_chat_message(int(target_chat), msg.message_id, disable_notification=True)
        pinned = True
    except Exception:
        pass
    payload = {"chat_id": int(target_chat), "message_id": int(msg.message_id), "pinned": pinned}
    if event: event.payload = json.dumps(payload, ensure_ascii=False)
    else: session.add(GameEvent(game_id=game.id, event_type="main_roster_message", payload=json.dumps(payload, ensure_ascii=False)))
    await session.commit()

async def delete_main_roster(bot, session, game) -> None:
    event = await _main_roster_event(session, game)
    if not event: return
    data = json.loads(event.payload or "{}")
    chat_id, message_id = data.get("chat_id"), data.get("message_id")
    if chat_id and message_id:
        try:
            if data.get("pinned"): await bot.unpin_chat_message(int(chat_id), int(message_id))
        except Exception: pass
        try: await bot.delete_message(int(chat_id), int(message_id))
        except Exception: pass
    await session.delete(event)
    await session.commit()

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
    roster_text = await _public_status_roster(session, game, include_state=False, full_header=False)
    if event and data.get("message_id"):
        try:
            await bot.edit_message_text(roster_text, chat_id=int(target_chat), message_id=int(data["message_id"]), parse_mode="HTML")
            return
        except Exception:
            pass
    try:
        msg = await bot.send_message(int(target_chat), roster_text, parse_mode="HTML")
    except Exception:
        return
    payload = {"round_no": int(round_no), "chat_id": int(target_chat), "message_id": msg.message_id}
    if event:
        event.payload = json.dumps(payload, ensure_ascii=False)
    else:
        session.add(GameEvent(game_id=game.id, event_type="round_roster_message",
                              payload=json.dumps(payload, ensure_ascii=False)))
    await session.commit()



async def _set_game_chat_lock(bot, session, game, locked: bool) -> None:
    """Apply the game's chat/night lock to the Telegram group when possible."""
    chat_id = await _group_chat_id(session, game)
    if not chat_id:
        return
    try:
        if locked:
            permissions = ChatPermissions(can_send_messages=False)
        else:
            permissions = ChatPermissions(
                can_send_messages=True,
                can_send_audios=True,
                can_send_documents=True,
                can_send_photos=True,
                can_send_videos=True,
                can_send_video_notes=True,
                can_send_voice_notes=True,
                can_send_polls=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True,
            )
        await bot.set_chat_permissions(chat_id, permissions)
    except Exception:
        # Telegram permissions require administrator rights; the DB setting
        # remains authoritative if the bot cannot change group permissions.
        pass

async def _send_night_menus(bot, session, game):
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
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.bot.send_message(
            callback.message.chat.id,
            "🎭 نقش‌ها پخش شد.\n\n👑 انتخاب سردست\n⚙️ تنظیمات بازی\n▶️ شروع دور",
            reply_markup=__import__("app.handlers.keyboards", fromlist=["leader_settings_keyboard"]).leader_settings_keyboard(game.game_key, game),
        )
        for _, role, user in assignments:
            try:
                await callback.bot.send_message(
                    user.telegram_id,
                    f"<b>نقش شما</b>\n\nنقش: {role.name_fa}\nتیم: {role.team}\n\n{role.description}",
                    parse_mode="HTML",
                )
            except Exception:
                pass
        await callback.answer("نقش‌ها پخش شد؛ مرحله انتخاب سردست آغاز شد.")


@router.callback_query(lambda c: c.data and c.data.startswith("night:") and not c.data.startswith("night:lock:") and not c.data.startswith("night:start_day:"))
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
            actor = await session.scalar(select(User).where(User.telegram_id == callback.from_user.id))
            if not actor or game.host_user_id != actor.id:
                await callback.answer("فقط گرداننده می‌تواند اقدامات شب را بررسی و ارسال کند.", show_alert=True)
                return
            ready = await night_ready(session, game)
            if ready:
                await callback.answer("اقدامات شب کامل است؛ حالا «شروع روز» را بزنید.")
            else:
                await _send_night_menus(callback.bot, session, game)
                await callback.answer("اقدامات شب برای بازیکنان ارسال شد؛ پس از ثبت همه اقدامات «شروع روز» را بزنید.")
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
            await callback.answer("اقدامات شب کامل شد؛ برای حل شب، «شروع روز» را بزنید.")
        else:
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
        await _refresh_turn_message(callback.bot, session, game, await current_turn(session, game.id))
        await callback.answer("درخواست چالش ثبت شد.")

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
        requester = await session.get(User, result["requester_id"])
        requester_name = requester.display_name or requester.first_name if requester else "بازیکن"
        await update_main_roster(callback.bot, session, game, await _group_chat_id(session, game))
        turn = await current_turn(session, game.id)
        turn_event, turn_data = await _turn_message(session, game, turn)
        if turn_event and turn_data:
            try:
                await callback.bot.edit_message_text(
                    f"🗣 نوبت صحبت {tg_mention(requester.telegram_id, requester_name)}\n\n"
                    "🤏🏻 <b>درخواست چالش انتخاب شد.</b>",
                    chat_id=int(turn_data["chat_id"]), message_id=int(turn_data["message_id"]),
                    reply_markup=None, parse_mode="HTML"
                )
            except Exception:
                pass
        chat_id = await _group_chat_id(session, game)
        if chat_id:
            await callback.bot.send_message(
                chat_id,
                f"🤏🏻 چالش به <b>{requester_name}</b> داده شد.",
                reply_markup=challenge_placement_keyboard(game.game_key, int(event_id), requester_name),
                parse_mode="HTML",
            )
        await callback.answer("چالش به بازیکن انتخاب‌شده داده شد.")


@router.callback_query(lambda c: c.data and c.data.startswith("challenge:select:"))
async def challenge_select_handler(callback: CallbackQuery):
    parts = callback.data.split(":")
    if len(parts) != 4 or not callback.from_user:
        return
    _, _, key, event_id = parts
    async with session_factory() as session:
        game = await _load(session, key)
        if not game or not callback.message:
            await callback.answer("بازی پیدا نشد.", show_alert=True)
            return
        event = await session.get(GameEvent, int(event_id))
        if not event or event.game_id != game.id:
            await callback.answer("درخواست چالش پیدا نشد.", show_alert=True)
            return
        data = json.loads(event.payload or "{}")
        requester = await session.get(User, int(data.get("requester_id", 0)))
        name = requester.display_name or requester.first_name if requester else "بازیکن"
        await callback.message.edit_reply_markup(reply_markup=challenge_placement_keyboard(game.game_key, int(event_id), name))
        await callback.answer("زمان اجرای چالش را انتخاب کنید.")


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
        turn_task = _turn_tasks.pop(game.game_key, None)
        if turn_task:
            turn_task.cancel()
        requester = await session.get(User, result["requester_id"])
        name = requester.display_name or requester.first_name if requester else "بازیکن"
        chat_id = await _group_chat_id(session, game)
        await callback.message.edit_text(
            f"🤏🏻 چالش به <b>{name}</b> داده شد.",
            parse_mode="HTML",
        )
        if chat_id:
            if result["placement"] == "before":
                challenge_turn = await current_turn(session, game.id)
                if challenge_turn:
                    try:
                        await callback.message.edit_text(
                            f"🤏🏻 چالش به <b>{name}</b> اجرا شد.",
                            parse_mode="HTML",
                        )
                    except Exception:
                        pass
                    challenge_msg = await _send_turn_message(
                        callback.bot, session, game, chat_id, challenge_turn
                    )
                    if challenge_msg:
                        await _schedule_turn_live(callback.bot, game.game_key)
                        await _schedule_auto_next(callback.bot, game.game_key, chat_id, challenge_msg.message_id)
            else:
                try:
                    await callback.message.edit_text(
                        f"🤏🏻 چالش به <b>{name}</b> داده شد.",
                        parse_mode="HTML",
                    )
                except Exception:
                    pass
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
        actor = (await session.execute(
            select(User).where(User.telegram_id == callback.from_user.id)
        )).scalar_one_or_none()
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
            if turn.get("kind") == "defense":
                await _finish_turn_message(callback.bot, session, game, turn)
                result = await advance_defense_turn(session, game)
                if result.get("finished"):
                    await _vote_target_message(callback.bot, session, game, callback.message.chat.id)
                    _vote_tasks[f"vote2:{key}"] = asyncio.create_task(
                        _vote2_timer(callback.bot, key, callback.message.chat.id)
                    )
                    await callback.answer("دفاع تمام شد؛ رای دوم آغاز شد.")
                    return
                await _send_defense_message(
                    callback.bot, session, game, callback.message.chat.id,
                    int(result["target_user_id"]),
                )
            else:
                await _finish_turn_message(callback.bot, session, game, turn)
                await _delete_turn_challenge_messages(callback.bot, session, game, turn)
                result = await next_turn(session, game)
        except ValueError as exc:
            await callback.answer(str(exc), show_alert=True)
            return
        chat_id = await _group_chat_id(session, game)
        if not chat_id:
            await callback.answer("گروه بازی پیدا نشد.", show_alert=True)
            return
        if result["kind"] == "finished_day":
            await callback.bot.send_message(
                chat_id,
                "🗳 نوبت‌های این دور تمام شد.",
                reply_markup=day_keyboard(game.game_key, await alive_players(session, game.id)),
            )
        elif result["kind"] == "defense":
            new_turn = await current_turn(session, game.id)
            if new_turn:
                await _send_defense_message(callback.bot, session, game, chat_id, int(new_turn["user_id"]))
        elif result["kind"] == "voting2":
            await _vote_target_message(callback.bot, session, game, chat_id)
            _vote_tasks[f"vote2:{game.game_key}"] = asyncio.create_task(_vote2_timer(callback.bot, game.game_key, chat_id))
        else:
            new_turn = await current_turn(session, game.id)
            if new_turn:
                await _send_turn_message(callback.bot, session, game, chat_id, new_turn)
                await _schedule_auto_next(callback.bot, game.game_key, chat_id)
        await callback.answer("نوبت بعدی شروع شد.")
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
        if game.phase == "day":
            if not turn or turn.get("status") != "finished":
                await callback.answer("ابتدا باید صحبت‌های دور تمام شود.", show_alert=True)
                return
        elif game.phase not in {"vote1_complete", "vote2_complete"}:
            await callback.answer("شروع فاز شب در این مرحله امکان‌پذیر نیست.", show_alert=True)
            return
        game.phase = "night"
        await session.commit()
        settings = await session.scalar(select(GroupSettings).where(GroupSettings.group_id == game.group_id))
        chat_id = await _group_chat_id(session, game)
        if chat_id:
            await _set_game_chat_lock(callback.bot, session, game, bool(settings and (settings.chat_lock or settings.night_lock)))
            await callback.bot.send_message(
                chat_id, "🌙 فاز شب آغاز شد.",
                reply_markup=continue_night_keyboard(game.game_key, settings.night_lock if settings else False, settings.chat_lock if settings else False),
            )
            await _send_night_menus(callback.bot, session, game)
        await callback.answer("فاز شب آغاز شد.")


@router.callback_query(lambda c: c.data and c.data.startswith("night:lock:"))
async def night_lock_handler(callback: CallbackQuery):
    parts = callback.data.split(":")
    if len(parts) != 4 or not callback.from_user:
        return
    _, _, key, field = parts
    async with session_factory() as session:
        game = await _load(session, key)
        actor = (await session.execute(select(User).where(User.telegram_id == callback.from_user.id))).scalar_one_or_none()
        if not game or not actor or game.host_user_id != actor.id or field not in {"night_lock", "chat_lock"}:
            await callback.answer("فقط گرداننده می‌تواند قفل‌ها را تغییر دهد.", show_alert=True)
            return
        settings = await session.scalar(select(GroupSettings).where(GroupSettings.group_id == game.group_id))
        if not settings:
            settings = GroupSettings(group_id=game.group_id)
            session.add(settings)
            await session.flush()
        setattr(settings, field, not bool(getattr(settings, field)))
        await session.commit()
        await callback.message.edit_reply_markup(reply_markup=continue_night_keyboard(game.game_key, settings.night_lock, settings.chat_lock))
        await _set_game_chat_lock(callback.bot, session, game, bool(settings.chat_lock or settings.night_lock))
        await callback.answer("تنظیم قفل ذخیره شد.")


@router.callback_query(lambda c: c.data and c.data.startswith("night:start_day:"))
async def night_start_day_handler(callback: CallbackQuery):
    key = callback.data.split(":", 2)[2]
    if not callback.from_user:
        return
    async with session_factory() as session:
        game = await _load(session, key)
        actor = (await session.execute(select(User).where(User.telegram_id == callback.from_user.id))).scalar_one_or_none()
        if not game or not actor or game.host_user_id != actor.id:
            await callback.answer("فقط گرداننده می‌تواند روز را شروع کند.", show_alert=True)
            return
        try:
            result = await resolve_night(session, game)
        except ValueError as exc:
            await callback.answer(str(exc), show_alert=True)
            return
        chat_id = await _group_chat_id(session, game)
        if result["winner"]:
            await send_game_result_notifications(callback.bot, session, game)
            if chat_id:
                await callback.bot.send_message(chat_id, "🏁 بازی تمام شد.")
            await delete_main_roster(callback.bot, session, game)
            await callback.message.edit_reply_markup(reply_markup=None)
            await callback.answer("بازی تمام شد.")
            return
        await start_new_day_round(session, game)
        settings = await session.scalar(select(GroupSettings).where(GroupSettings.group_id == game.group_id))
        if chat_id:
            await _set_game_chat_lock(callback.bot, session, game, bool(settings and settings.chat_lock))

            await update_round_roster(callback.bot, session, game, chat_id)
            await update_main_roster(callback.bot, session, game, chat_id)
            await callback.bot.send_message(chat_id, f"🌅 روز جدید شروع شد. دور {await current_round(session, game.id)}")
            await _send_turn_message(callback.bot, session, game, chat_id)
            await _schedule_auto_next(callback.bot, game.game_key, chat_id)
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.answer("روز جدید شروع شد.")

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
        if game.host_user_id != actor.id:
            await callback.answer("فقط گرداننده می‌تواند بازی را تمام کند.", show_alert=True)
            return
        turn = await current_turn(session, game.id)
        if not turn or turn.get("status") != "finished":
            await callback.answer("تا پایان نوبت‌های این دور امکان اتمام بازی نیست.", show_alert=True)
            return
        await callback.message.edit_text("🏁 <b>تعیین برنده بازی</b>\n\nتیم برنده را انتخاب کنید:", reply_markup=finish_game_keyboard(game.group_id), parse_mode="HTML")
        await callback.answer("نتیجه نهایی را انتخاب کنید.")


_vote_tasks = {}
_vote_transition_locks = {}

def _vote_time(dt: datetime) -> str:
    local = dt.astimezone() if dt.tzinfo else dt
    return local.strftime("%H:%M - %S:%f")[:-4]

async def _set_latest_vote_state_message(session, game, chat_id: int, message_id: int):
    result = await session.execute(select(GameEvent).where(
        GameEvent.game_id == game.id, GameEvent.event_type == "vote_state"
    ).order_by(GameEvent.id.desc()))
    event = result.scalars().first()
    if not event:
        return
    data = json.loads(event.payload or "{}")
    data["chat_id"] = chat_id
    data["message_id"] = message_id
    event.payload = json.dumps(data, ensure_ascii=False)
    await session.commit()

async def _send_vote2_private_controls(bot, session, game):
    state = await _latest_vote_state(session, game.id)
    if not state or state.get("phase") != "vote2":
        return
    rules = state.get("rules") or {}
    visibility = rules.get("visibility", "public")
    candidates = [int(x) for x in state.get("queue", [])]
    users = {}
    for uid in candidates:
        user = await session.get(User, uid)
        if user:
            users[uid] = user
    candidate_buttons = [
        (uid, users[uid].display_name or users[uid].first_name or "بازیکن")
        for uid in candidates if uid in users
    ]
    eligible = [int(x) for x in rules.get("eligible_voter_ids", [])]
    if visibility == "host_private":
        host = await session.get(User, int(game.host_user_id)) if game.host_user_id else None
        if host:
            voters = []
            for uid in eligible:
                user = await session.get(User, uid)
                if user:
                    voters.append((uid, user.display_name or user.first_name or "بازیکن"))
            voted = {
                int(voter_id) for voter_id, _ in await _vote_records_for_phase(session, game, int(state["round_no"]), "vote2")
            }
            await bot.send_message(
                host.telegram_id,
                "🗳 رای دوم مخفی\n\nابتدا رأی‌دهنده را انتخاب کنید:",
                reply_markup=vote2_private_voters_keyboard(game.game_key, voters, voted),
            )
    elif visibility == "bot_private":
        for uid in eligible:
            user = await session.get(User, uid)
            if not user:
                continue
            try:
                await bot.send_message(
                    user.telegram_id,
                    "🗳 رای دوم مخفی\n\nیکی از مدافعان را برای خروج انتخاب کنید:",
                    reply_markup=vote2_private_targets_keyboard(game.game_key, uid, candidate_buttons),
                )
            except Exception:
                # A user who has not started the bot privately cannot receive
                # the ballot. Their missing ballot does not change the
                # electorate denominator.
                pass


async def _vote_target_message(bot, session, game, chat_id: int):
    state = await _latest_vote_state(session, game.id)
    if not state or state.get("phase") not in {"vote1", "vote2"} or state.get("status") != "active":
        return None
    phase = state["phase"]
    round_no = int(state["round_no"])
    if phase == "vote2" and (state.get("rules") or {}).get("visibility", "public") != "public":
        visibility = (state.get("rules") or {}).get("visibility")
        label = "گرداننده" if visibility == "host_private" else "ربات"
        msg = await bot.send_message(
            chat_id,
            f"🗳 رای گیری دوم مخفی است. ثبت رای توسط {label} در PV انجام می‌شود.",
            reply_markup=vote2_complete_keyboard(game.game_key),
        )
        await _set_latest_vote_state_message(session, game, chat_id, msg.message_id)
        await _send_vote2_private_controls(bot, session, game)
        return msg
    if phase == "vote1":
        target_id = int(state["target_user_id"])
        target = await session.get(User, target_id)
        if not target:
            return None
        records = await _vote_records_for_target(session, game, round_no, phase, target_id)
        lines = [
            f"🗳 رای برای {tg_mention(target.telegram_id, target.display_name or target.first_name or 'بازیکن')}",
            "",
            "کسانی که رای دادن:",
        ]
        if records:
            lines.extend(f"• {tg_mention(user.telegram_id, user.display_name or user.first_name or 'بازیکن')} — {_vote_time(vote.created_at)}" for vote, user in records)
        else:
            lines.append("هنوز کسی رای نداده")
        markup = vote1_target_keyboard(game.game_key, target_id)
    else:
        candidates = [int(x) for x in state.get("queue", [])]
        records = await _vote_records_for_phase(session, game, round_no, phase)
        selected_by = {int(vote.voter_user_id): int(vote.target_user_id) for vote, _ in records}
        users = {}
        for uid in candidates:
            user = await session.get(User, uid)
            if user:
                users[uid] = user
        lines = ["🗳 رای گیری دوم", "", "مدافعان:"]
        for uid in candidates:
            user = users.get(uid)
            if user:
                lines.append(f"• {tg_mention(user.telegram_id, user.display_name or user.first_name or 'بازیکن')}")
        lines += ["", "کسانی که رای دادن:"]
        if records:
            for vote, user in records:
                target = users.get(int(vote.target_user_id))
                target_name = target.display_name or target.first_name or "بازیکن" if target else str(vote.target_user_id)
                lines.append(
                    f"• {tg_mention(user.telegram_id, user.display_name or user.first_name or 'بازیکن')} → {target_name} — {_vote_time(vote.created_at)}"
                )
        else:
            lines.append("هنوز کسی رای نداده")
        markup = vote2_ballot_keyboard(
            game.game_key,
            [(uid, users[uid].display_name or users[uid].first_name or "بازیکن") for uid in candidates if uid in users],
        )
    msg = await bot.send_message(chat_id, "\n".join(lines), reply_markup=markup, parse_mode="HTML")
    await _set_latest_vote_state_message(session, game, chat_id, msg.message_id)
    return msg


async def _refresh_vote_target_message(bot, session, game):
    state = await _latest_vote_state(session, game.id)
    if not state or state.get("phase") not in {"vote1", "vote2"} or state.get("status") != "active":
        return
    chat_id, message_id = state.get("chat_id"), state.get("message_id")
    if not chat_id or not message_id:
        return
    phase = state["phase"]
    round_no = int(state["round_no"])
    if phase == "vote1":
        target_id = int(state["target_user_id"])
        target = await session.get(User, target_id)
        if not target:
            return
        records = await _vote_records_for_target(session, game, round_no, phase, target_id)
        lines = [
            f"🗳 رای برای {tg_mention(target.telegram_id, target.display_name or target.first_name or 'بازیکن')}",
            "",
            "کسانی که رای دادن:",
        ]
        if records:
            lines.extend(f"• {tg_mention(user.telegram_id, user.display_name or user.first_name or 'بازیکن')} — {_vote_time(vote.created_at)}" for vote, user in records)
        else:
            lines.append("هنوز کسی رای نداده")
        markup = vote1_target_keyboard(game.game_key, target_id)
    else:
        candidates = [int(x) for x in state.get("queue", [])]
        records = await _vote_records_for_phase(session, game, round_no, phase)
        users = {}
        for uid in candidates:
            user = await session.get(User, uid)
            if user:
                users[uid] = user
        lines = ["🗳 رای گیری دوم", "", "مدافعان:"]
        for uid in candidates:
            if uid in users:
                user = users[uid]
                lines.append(f"• {tg_mention(user.telegram_id, user.display_name or user.first_name or 'بازیکن')}")
        lines += ["", "کسانی که رای دادن:"]
        if records:
            for vote, user in records:
                target = users.get(int(vote.target_user_id))
                target_name = target.display_name or target.first_name or "بازیکن" if target else str(vote.target_user_id)
                lines.append(
                    f"• {tg_mention(user.telegram_id, user.display_name or user.first_name or 'بازیکن')} → {target_name} — {_vote_time(vote.created_at)}"
                )
        else:
            lines.append("هنوز کسی رای نداده")
        markup = vote2_ballot_keyboard(
            game.game_key,
            [(uid, users[uid].display_name or users[uid].first_name or "بازیکن") for uid in candidates if uid in users],
        )
    try:
        await bot.edit_message_text("\n".join(lines), chat_id=int(chat_id), message_id=int(message_id), reply_markup=markup, parse_mode="HTML")
    except Exception:
        pass


async def _finish_vote_message(bot, session, game, *, next_button: bool, final: bool = False):
    state = await _latest_vote_state(session, game.id)
    if not state or not state.get("message_id"):
        return
    phase = state.get("phase")
    if phase == "vote2":
        records = await _vote_records_for_phase(session, game, int(state["round_no"]), "vote2")
        counts = {int(uid): 0 for uid in state.get("queue", [])}
        for vote, _user in records:
            counts[int(vote.target_user_id)] = counts.get(int(vote.target_user_id), 0) + 1
        lines = ["پایان زمان رای گیری دوم", ""]
        for uid in state.get("queue", []):
            user = await session.get(User, int(uid))
            if user:
                lines.append(f"• {tg_mention(user.telegram_id, user.display_name or user.first_name or 'بازیکن')}: {counts.get(int(uid), 0)} رای")
        result = state.get("result") or {}
        if state.get("status") == "active":
            lines += ["", "⏱ زمان رای تمام شد.", "برای تعیین نتیجه، گرداننده «اتمام رای گیری» را بزند."]
        else:
            eliminated = result.get("eliminated_ids", [])
            if eliminated:
                names = []
                for uid in eliminated:
                    user = await session.get(User, int(uid))
                    if user:
                        names.append(tg_mention(user.telegram_id, user.display_name or user.first_name or "بازیکن"))
                lines += ["", "خارج شده:", "، ".join(names)]
            else:
                lines += ["", "در این رای خروجی ثبت نشد."]
        try:
            await bot.edit_message_text("\n".join(lines), chat_id=int(state["chat_id"]), message_id=int(state["message_id"]), reply_markup=vote2_complete_keyboard(game.game_key), parse_mode="HTML")
        except Exception:
            pass
        return

    target = await session.get(User, int(state["target_user_id"]))
    records = await _vote_records_for_target(session, game, int(state["round_no"]), state["phase"], int(state["target_user_id"]))
    lines = [f"پایان زمان رای به {tg_mention(target.telegram_id, target.display_name or target.first_name or 'بازیکن')}", f"تعداد رای {len(records)}", "", "کسایی که رای دادن"]
    if records:
        lines.extend(f"• {tg_mention(user.telegram_id, user.display_name or user.first_name or 'بازیکن')}" for _, user in records)
    else:
        lines.append("کسی رای نداده است")
    if final:
        markup = vote2_complete_keyboard(game.game_key)
    elif next_button:
        markup = vote1_complete_keyboard(game.game_key) if state.get("index", 0) + 1 >= len(state.get("queue", [])) else InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="بازیکن بعدی", callback_data=f"vote1:next:{game.game_key}")]])
    else:
        markup = None
    try:
        await bot.edit_message_text("\n".join(lines), chat_id=int(state["chat_id"]), message_id=int(state["message_id"]), reply_markup=markup, parse_mode="HTML")
    except Exception:
        pass

async def _start_vote1_after_delay(bot, game_key: str, chat_id: int, delay: int):
    await asyncio.sleep(max(0, delay))
    async with session_factory() as session:
        game = await _load(session, game_key)
        if not game or game.status != "running":
            return
        if game.phase not in {"day", "vote_setup"}:
            return
        await vote1_start(session, game)
        await _vote_target_message(bot, session, game, chat_id)
        _vote_tasks[game_key] = asyncio.create_task(_vote1_timer(bot, game_key, chat_id))

async def _vote1_timer(bot, game_key: str, chat_id: int):
    try:
        while True:
            async with session_factory() as session:
                game = await _load(session, game_key)
                if not game or game.phase != "voting1": return
                state = await _latest_vote_state(session, game.id)
                started = datetime.fromisoformat(state["started_at"])
                remaining = max(0.0, float(game.vote_seconds or 10) - (datetime.now(timezone.utc) - started).total_seconds())
            if remaining > 0:
                await asyncio.sleep(min(remaining, 0.2))
                continue
            async with session_factory() as session:
                game = await _load(session, game_key)
                if not game or game.phase != "voting1": return
                state_before = await _latest_vote_state(session, game.id)
                if not state_before:
                    return
                lock = _vote_transition_locks.setdefault(game_key, asyncio.Lock())
                async with lock:
                    state_locked = await _latest_vote_state(session, game.id)
                    if not state_locked or state_locked.get("phase") != "vote1":
                        return
                    if state_locked.get("status") == "active":
                        await finish_vote1_target(session, game)
                    is_last = int(state_locked.get("index", 0)) + 1 >= len(state_locked.get("queue", []))
                    await _finish_vote_message(bot, session, game, next_button=False)
                    result = await advance_vote1(session, game)
                if result["finished"] or is_last:
                    if result.get("finished"):
                        state_after = await _latest_vote_state(session, game.id)
                        message_id = state_after.get("message_id") if state_after else None
                        if message_id:
                            try:
                                await bot.edit_message_reply_markup(
                                    chat_id=chat_id,
                                    message_id=int(message_id),
                                    reply_markup=vote1_complete_keyboard(game.game_key),
                                )
                            except Exception:
                                pass
                    return
                if game.voting_mode == "auto":
                    await _vote_target_message(bot, session, game, chat_id)
                    continue
                return
    except asyncio.CancelledError:
        return
    finally:
        current_task = _vote_tasks.get(game_key)
        if current_task is asyncio.current_task():
            _vote_tasks.pop(game_key, None)

@router.callback_query(lambda c: c.data and c.data.startswith("day:vote:"))
async def day_vote_handler(callback: CallbackQuery):
    key = callback.data.split(":", 2)[2]
    async with session_factory() as session:
        game = await _load(session, key)
        actor = (await session.execute(select(User).where(User.telegram_id == callback.from_user.id))).scalar_one_or_none() if callback.from_user else None
        if not game or not actor or game.host_user_id != actor.id:
            await callback.answer("فقط گرداننده می‌تواند تنظیمات رای گیری را باز کند.", show_alert=True)
            return
        game.phase = "vote_setup"
        await session.commit()
        await callback.message.edit_text("🗳 <b>تنظیمات رای گیری</b>", reply_markup=voting_setup_keyboard(game.game_key, game.voting_pre_delay_seconds, game.vote_seconds, game.voting_mode), parse_mode="HTML")
    await callback.answer()

@router.callback_query(lambda c: c.data and c.data.startswith("votingset:"))
async def voting_settings_handler(callback: CallbackQuery):
    parts = callback.data.split(":")
    if not callback.from_user: return
    key = parts[2] if len(parts) > 2 else ""
    async with session_factory() as session:
        game = await _load(session, key)
        actor = (await session.execute(select(User).where(User.telegram_id == callback.from_user.id))).scalar_one_or_none()
        if not game or not actor or game.host_user_id != actor.id:
            await callback.answer("فقط گرداننده می‌تواند تنظیمات رای گیری را تغییر دهد.", show_alert=True); return
        action = parts[1] if len(parts) > 1 else ""
        if action == "menu":
            await callback.message.edit_text("🗳 <b>تنظیمات رای گیری</b>", reply_markup=voting_setup_keyboard(key, game.voting_pre_delay_seconds, game.vote_seconds, game.voting_mode), parse_mode="HTML")
        elif action == "delay":
            await callback.message.edit_text("زمان انتظار قبل از شروع رای:", reply_markup=voting_delay_keyboard(key, game.voting_pre_delay_seconds))
        elif action == "duration":
            await callback.message.edit_text("زمان هر رای:", reply_markup=voting_duration_keyboard(key, game.vote_seconds))
        elif action == "mode":
            await callback.message.edit_text("نوع رای گیری:", reply_markup=voting_mode_keyboard(key, game.voting_mode))
        elif action == "set_delay":
            game.voting_pre_delay_seconds = int(parts[3]); await session.commit()
            await callback.message.edit_text("🗳 <b>تنظیمات رای گیری</b>", reply_markup=voting_setup_keyboard(key, game.voting_pre_delay_seconds, game.vote_seconds, game.voting_mode), parse_mode="HTML")
        elif action == "set_duration":
            game.vote_seconds = int(parts[3]); await session.commit()
            await callback.message.edit_text("🗳 <b>تنظیمات رای گیری</b>", reply_markup=voting_setup_keyboard(key, game.voting_pre_delay_seconds, game.vote_seconds, game.voting_mode), parse_mode="HTML")
        elif action == "set_mode":
            game.voting_mode = parts[3]; await session.commit()
            await callback.message.edit_text("🗳 <b>تنظیمات رای گیری</b>", reply_markup=voting_setup_keyboard(key, game.voting_pre_delay_seconds, game.vote_seconds, game.voting_mode), parse_mode="HTML")
        elif action == "revoke":
            players = await alive_players(session, game.id)
            revoked = await _revoked_vote_ids(session, game.id, await current_round(session, game.id))
            await callback.message.edit_text("بازیکنی را که می‌خواهید حق رای او گرفته شود انتخاب کنید:", reply_markup=vote_rights_keyboard(key, players, revoked))
        elif action == "revoke_target":
            uid = int(parts[3]); user = await session.get(User, uid)
            await callback.message.edit_text(f"حق رای <b>{tg_name(user.display_name or user.first_name)}</b> گرفته شود؟", reply_markup=vote_right_confirm_keyboard(key, uid), parse_mode="HTML")
        elif action == "confirm_revoke":
            uid = int(parts[3]); round_no = await current_round(session, game.id)
            await _event(session, game, "vote_right_revoked", {"round_no": round_no, "user_id": uid, "active": True}, actor.id)
            await session.commit()
            await callback.message.edit_text("حق رای بازیکن برای این دور گرفته شد.", reply_markup=voting_setup_keyboard(key, game.voting_pre_delay_seconds, game.vote_seconds, game.voting_mode), parse_mode="HTML")
        await callback.answer()

@router.callback_query(lambda c: c.data and c.data.startswith("vote:start1:"))
async def vote_start1_handler(callback: CallbackQuery):
    key = callback.data.split(":", 2)[2]
    if not callback.from_user: return
    async with session_factory() as session:
        game = await _load(session, key)
        actor = (await session.execute(select(User).where(User.telegram_id == callback.from_user.id))).scalar_one_or_none()
        if not game or actor is None or game.host_user_id != actor.id:
            await callback.answer("فقط گرداننده می‌تواند رای گیری را شروع کند.", show_alert=True); return
        delay = int(game.voting_pre_delay_seconds or 0)
        if delay:
            await callback.message.edit_text(f"🗳 رای گیری بعد از <b>{delay} ثانیه</b> شروع می‌شود.", parse_mode="HTML")
            task = asyncio.create_task(_start_vote1_after_delay(callback.bot, key, callback.message.chat.id, delay))
            _vote_tasks[key] = task
        else:
            await vote1_start(session, game)
            await _vote_target_message(callback.bot, session, game, callback.message.chat.id)
            _vote_tasks[key] = asyncio.create_task(_vote1_timer(callback.bot, key, callback.message.chat.id))
    await callback.answer()

@router.callback_query(lambda c: c.data and c.data.startswith("vote1:cast:"))
async def vote1_cast_handler(callback: CallbackQuery):
    parts = callback.data.split(":"); key, target_id = parts[2], int(parts[3])
    async with session_factory() as session:
        game = await _load(session, key); actor = (await session.execute(select(User).where(User.telegram_id == callback.from_user.id))).scalar_one_or_none() if callback.from_user else None
        if not game or not actor: await callback.answer("بازی پیدا نشد.", show_alert=True); return
        try: await cast_vote_phase(session, game, actor, target_id, "vote1")
        except ValueError as exc: await callback.answer(str(exc), show_alert=True); return
        await _refresh_vote_target_message(callback.bot, session, game)
    await callback.answer("رای ثبت شد.")

@router.callback_query(lambda c: c.data and c.data.startswith("vote1:next:"))
async def vote1_next_handler(callback: CallbackQuery):
    key = callback.data.split(":", 2)[2]
    async with session_factory() as session:
        game = await _load(session, key); actor = (await session.execute(select(User).where(User.telegram_id == callback.from_user.id))).scalar_one_or_none() if callback.from_user else None
        if not game or not actor or game.host_user_id != actor.id: await callback.answer("فقط گرداننده.", show_alert=True); return
        lock = _vote_transition_locks.setdefault(key, asyncio.Lock())
        async with lock:
            task = _vote_tasks.pop(key, None)
            if task and task is not asyncio.current_task():
                task.cancel()
            state = await _latest_vote_state(session, game.id)
            if not state or state.get("phase") != "vote1":
                await callback.answer("این رأی‌گیری دیگر فعال نیست.", show_alert=True)
                return
            # First freeze the current result in its own message. Only its
            # buttons are removed; the next target gets a fresh message.
            if state.get("status") == "active":
                await finish_vote1_target(session, game)
            await _finish_vote_message(bot=callback.bot, session=session, game=game, next_button=False)
            result = await advance_vote1(session, game)
            if result["finished"]:
                await callback.message.edit_reply_markup(reply_markup=vote1_complete_keyboard(key))
            else:
                await _vote_target_message(callback.bot, session, game, callback.message.chat.id)
                _vote_tasks[key] = asyncio.create_task(_vote1_timer(callback.bot, key, callback.message.chat.id))
    await callback.answer("بازیکن بعدی آماده شد." if not result["finished"] else "رأی اول تمام شد.")

@router.callback_query(lambda c: c.data and c.data.startswith("vote1:finish:"))
async def vote1_finish_handler(callback: CallbackQuery):
    key = callback.data.split(":", 2)[2]
    if not callback.from_user:
        return
    async with session_factory() as session:
        game = await _load(session, key)
        actor = (await session.execute(
            select(User).where(User.telegram_id == callback.from_user.id)
        )).scalar_one_or_none()
        if not game or not actor or game.host_user_id != actor.id:
            await callback.answer("فقط گرداننده.", show_alert=True)
            return
        task = _vote_tasks.pop(key, None)
        if task:
            task.cancel()
        result = await advance_vote1(session, game)
        if result["finished"]:
            await callback.message.edit_text(
                "🗳 <b>رأی اول تمام شد</b>\n\nاز گزینه‌های زیر مرحله بعد را انتخاب کنید.",
                reply_markup=vote1_complete_keyboard(key),
                parse_mode="HTML",
            )
        else:
            await _vote_target_message(callback.bot, session, game, callback.message.chat.id)
            _vote_tasks[key] = asyncio.create_task(
                _vote1_timer(callback.bot, key, callback.message.chat.id)
            )
    await callback.answer()

@router.callback_query(lambda c: c.data and c.data.startswith("vote2:select:"))
async def vote2_select_handler(callback: CallbackQuery):
    parts = callback.data.split(":"); key, uid = parts[2], int(parts[3])
    async with session_factory() as session:
        game = await _load(session, key); actor = (await session.execute(select(User).where(User.telegram_id == callback.from_user.id))).scalar_one_or_none() if callback.from_user else None
        if not game or not actor or game.host_user_id != actor.id: await callback.answer("فقط گرداننده.", show_alert=True); return
        selected = await toggle_vote2_candidate(session, game, uid)
        state = await _latest_vote_state(session, game.id)
        pool = {int(x) for x in (state or {}).get("defense_pool_candidates", (state or {}).get("qualified_candidates", []))}
        players = [row for row in await alive_players(session, game.id) if row[1].id in pool]
        records = await _vote_records_for_phase(session, game, int((state or {}).get("round_no", await current_round(session, game.id))), "vote1")
        counts = {}
        for vote, _user in records:
            counts[int(vote.target_user_id)] = counts.get(int(vote.target_user_id), 0) + 1
        await callback.message.edit_reply_markup(reply_markup=defense_selection_keyboard(key, players, set(selected), counts))
    await callback.answer()

async def _send_defense_message(bot, session, game, chat_id: int, user_id: int):
    user = await session.get(User, user_id)
    if not user:
        return None
    turn = await current_turn(session, game.id)
    if not turn:
        return None
    msg = await bot.send_message(
        chat_id,
        f"🛡 نوبت دفاع {tg_mention(user.telegram_id, user.display_name or user.first_name or 'بازیکن')}\n\n⏱ {_duration_text(game.turn_seconds)}",
        reply_markup=day_turn_keyboard(game.game_key, True, False, game.turn_color_enabled, game.turn_color, game.challenge_color, False, False),
        parse_mode="HTML",
    )
    await _register_turn_message(session, game, chat_id=chat_id, message_id=msg.message_id, turn=turn)
    await _schedule_turn_live(bot, game.game_key)
    return msg


@router.callback_query(lambda c: c.data and c.data.startswith("vote2:start:"))
async def vote2_setup_handler(callback: CallbackQuery):
    key = callback.data.split(":", 2)[2]
    if not callback.from_user:
        return
    async with session_factory() as session:
        game = await _load(session, key)
        actor = (await session.execute(select(User).where(User.telegram_id == callback.from_user.id))).scalar_one_or_none()
        if not game or not actor or game.host_user_id != actor.id:
            await callback.answer("فقط گرداننده.", show_alert=True)
            return
        await callback.message.edit_text("🗳 <b>تنظیمات رای گیری دوم</b>", reply_markup=vote2_setup_keyboard(key, game.vote2_selection_mode), parse_mode="HTML")
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("vote2:mode:"))
async def vote2_mode_handler(callback: CallbackQuery):
    key = callback.data.split(":", 2)[2]
    if not callback.from_user:
        return
    async with session_factory() as session:
        game = await _load(session, key)
        actor = (await session.execute(select(User).where(User.telegram_id == callback.from_user.id))).scalar_one_or_none()
        if not game or not actor or game.host_user_id != actor.id:
            await callback.answer("فقط گرداننده.", show_alert=True)
            return
        game.vote2_selection_mode = "auto" if game.vote2_selection_mode == "manual" else "manual"
        await session.commit()
        await callback.message.edit_reply_markup(reply_markup=vote2_setup_keyboard(key, game.vote2_selection_mode))
    await callback.answer("نوع رای گیری دوم تغییر کرد.")


@router.callback_query(lambda c: c.data and c.data.startswith("vote2:choose:"))
async def vote2_choose_handler(callback: CallbackQuery):
    key = callback.data.split(":", 2)[2]
    if not callback.from_user:
        return
    async with session_factory() as session:
        game = await _load(session, key)
        actor = (await session.execute(select(User).where(User.telegram_id == callback.from_user.id))).scalar_one_or_none()
        if not game or not actor or game.host_user_id != actor.id:
            await callback.answer("فقط گرداننده.", show_alert=True)
            return
        state = await _latest_vote_state(session, game.id)
        pool = {int(x) for x in (state or {}).get("defense_pool_candidates", (state or {}).get("qualified_candidates", []))}
        players = [row for row in await alive_players(session, game.id) if row[1].id in pool]
        selected = {int(x) for x in (state or {}).get("defense_candidates", [])}
        records = await _vote_records_for_phase(session, game, int((state or {}).get("round_no", await current_round(session, game.id))), "vote1")
        counts = {}
        for vote, _user in records:
            counts[int(vote.target_user_id)] = counts.get(int(vote.target_user_id), 0) + 1
        await callback.message.edit_text("بازیکنان دارای حداقل یک رأی را برای دفاع انتخاب کنید:", reply_markup=defense_selection_keyboard(key, players, selected, counts))
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("vote2:begin:"))
async def vote2_begin_handler(callback: CallbackQuery):
    key = callback.data.split(":", 2)[2]
    if not callback.from_user:
        return
    async with session_factory() as session:
        game = await _load(session, key)
        actor = (await session.execute(select(User).where(User.telegram_id == callback.from_user.id))).scalar_one_or_none()
        if not game or not actor or game.host_user_id != actor.id:
            await callback.answer("فقط گرداننده.", show_alert=True)
            return
        try:
            first_defender = await start_vote2(session, game)
        except ValueError as exc:
            await callback.answer(str(exc), show_alert=True)
            return
        await _send_defense_message(callback.bot, session, game, callback.message.chat.id, int(first_defender))
    await callback.answer("دور دفاع شروع شد.")


async def _vote2_timer(bot, game_key: str, chat_id: int):
    try:
        while True:
            async with session_factory() as session:
                game = await _load(session, game_key)
                if not game or game.phase != "voting2":
                    return
                state = await _latest_vote_state(session, game.id)
                if not state or state.get("phase") != "vote2" or state.get("status") != "active":
                    return
                started = datetime.fromisoformat(state["started_at"])
                remaining = max(0.0, float(game.vote_seconds or 10) - (datetime.now(timezone.utc) - started).total_seconds())
            if remaining > 0:
                await asyncio.sleep(min(remaining, 0.2))
                continue
            async with session_factory() as session:
                game = await _load(session, game_key)
                if not game or game.phase != "voting2":
                    return
                state = await _latest_vote_state(session, game.id)
                if not state:
                    return
                if game.voting_mode == "auto":
                    await finish_vote2(session, game)
                    await update_main_roster(bot, session, game, chat_id)
                    await _finish_vote_message(bot, session, game, next_button=False, final=True)
                else:
                    await _finish_vote_message(bot, session, game, next_button=False, final=True)
                return
    except asyncio.CancelledError:
        return
    finally:
        _vote_tasks.pop(f"vote2:{game_key}", None)


@router.callback_query(lambda c: c.data and c.data.startswith("vote2:next:"))
async def vote2_next_handler(callback: CallbackQuery):
    key = callback.data.split(":", 2)[2]
    if not callback.from_user:
        return
    async with session_factory() as session:
        game = await _load(session, key)
        actor = (await session.execute(select(User).where(User.telegram_id == callback.from_user.id))).scalar_one_or_none()
        if not game or not actor or game.host_user_id != actor.id:
            await callback.answer("فقط گرداننده می‌تواند رای را تمام کند.", show_alert=True)
            return
        task = _vote_tasks.pop(f"vote2:{key}", None)
        if task:
            task.cancel()
        result = await advance_vote2(session, game)
        await update_main_roster(callback.bot, session, game, await _group_chat_id(session, game))
        await _finish_vote_message(callback.bot, session, game, next_button=False, final=True)
        if result["finished"]:
            await callback.answer("رای گیری دوم تمام شد.")
            return
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("vote2:private:voter:"))
async def vote2_private_voter_handler(callback: CallbackQuery):
    parts = callback.data.split(":")
    if len(parts) != 5 or not callback.from_user:
        return
    key, voter_id = parts[3], int(parts[4])
    async with session_factory() as session:
        game = await _load(session, key)
        actor = (await session.execute(select(User).where(User.telegram_id == callback.from_user.id))).scalar_one_or_none()
        if not game or not actor or game.host_user_id != actor.id:
            await callback.answer("فقط گرداننده.", show_alert=True)
            return
        state = await _latest_vote_state(session, game.id)
        if not state or state.get("phase") != "vote2" or state.get("status") != "active":
            await callback.answer("رای دوم فعال نیست.", show_alert=True)
            return
        candidates = []
        for uid in state.get("queue", []):
            user = await session.get(User, int(uid))
            if user:
                candidates.append((int(uid), user.display_name or user.first_name or "بازیکن"))
        voter = await session.get(User, voter_id)
        if not voter:
            await callback.answer("رأی‌دهنده پیدا نشد.", show_alert=True)
            return
        await callback.message.edit_text(
            f"🗳 رأی برای {tg_mention(voter.telegram_id, voter.display_name or voter.first_name or 'بازیکن')}",
            reply_markup=vote2_private_targets_keyboard(key, voter_id, candidates),
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("vote2:private:cast:"))
async def vote2_private_cast_handler(callback: CallbackQuery):
    parts = callback.data.split(":")
    if len(parts) != 6 or not callback.from_user:
        return
    key, voter_id, target_id = parts[3], int(parts[4]), int(parts[5])
    async with session_factory() as session:
        game = await _load(session, key)
        actor = (await session.execute(select(User).where(User.telegram_id == callback.from_user.id))).scalar_one_or_none()
        if not game or not actor or game.host_user_id != actor.id:
            await callback.answer("فقط گرداننده.", show_alert=True)
            return
        try:
            voter = await session.get(User, voter_id)
            if not voter:
                raise ValueError("رأی‌دهنده پیدا نشد.")
            await cast_vote_phase(session, game, actor, target_id, "vote2", voter_id=voter_id)
        except ValueError as exc:
            await callback.answer(str(exc), show_alert=True)
            return
        await callback.message.edit_text("✅ رای این بازیکن ثبت شد.")
    await callback.answer("رای ثبت شد.")


@router.callback_query(lambda c: c.data and c.data.startswith("vote2:private:panel:"))
async def vote2_private_panel_handler(callback: CallbackQuery):
    key = callback.data.split(":", 3)[3]
    if not callback.from_user:
        return
    async with session_factory() as session:
        game = await _load(session, key)
        actor = (await session.execute(select(User).where(User.telegram_id == callback.from_user.id))).scalar_one_or_none()
        if not game or not actor or game.host_user_id != actor.id:
            await callback.answer("فقط گرداننده.", show_alert=True)
            return
        state = await _latest_vote_state(session, game.id)
        if not state:
            await callback.answer("رای دوم فعال نیست.", show_alert=True)
            return
        voters = []
        for uid in state.get("rules", {}).get("eligible_voter_ids", []):
            user = await session.get(User, int(uid))
            if user:
                voters.append((int(uid), user.display_name or user.first_name or "بازیکن"))
        voted = {int(v.voter_user_id) for v, _ in await _vote_records_for_phase(session, game, int(state["round_no"]), "vote2")}
        await callback.message.edit_text(
            "🗳 رای دوم مخفی\n\nرأی‌دهنده را انتخاب کنید:",
            reply_markup=vote2_private_voters_keyboard(key, voters, voted),
        )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("vote2:cast:"))
async def vote2_cast_handler(callback: CallbackQuery):
    parts = callback.data.split(":"); key, target_id = parts[2], int(parts[3])
    async with session_factory() as session:
        game = await _load(session, key); actor = (await session.execute(select(User).where(User.telegram_id == callback.from_user.id))).scalar_one_or_none() if callback.from_user else None
        if not game or not actor: await callback.answer("بازی پیدا نشد.", show_alert=True); return
        try: await cast_vote_phase(session, game, actor, target_id, "vote2")
        except ValueError as exc: await callback.answer(str(exc), show_alert=True); return
        state = await _latest_vote_state(session, game.id)
        if (state.get("rules") or {}).get("visibility", "public") == "public":
            await _refresh_vote_target_message(callback.bot, session, game)
        else:
            try:
                await callback.message.edit_text("✅ رای شما ثبت شد.")
            except Exception:
                pass
    await callback.answer("رای ثبت شد.")

@router.callback_query(lambda c: c.data and c.data.startswith("vote2:finish:"))
async def vote2_finish_handler(callback: CallbackQuery):
    key = callback.data.split(":", 2)[2]
    async with session_factory() as session:
        game = await _load(session, key); actor = (await session.execute(select(User).where(User.telegram_id == callback.from_user.id))).scalar_one_or_none() if callback.from_user else None
        if not game or not actor or game.host_user_id != actor.id: await callback.answer("فقط گرداننده.", show_alert=True); return
        result = await advance_vote2(session, game)
        if result["finished"]:
            await callback.message.edit_reply_markup(reply_markup=vote2_result_keyboard(key))
            await callback.message.answer("🗳 رای گیری دوم تمام شد.")
        else:
            await _vote_target_message(callback.bot, session, game, callback.message.chat.id)
            _vote_tasks[f"vote2:{key}"] = asyncio.create_task(_vote2_timer(callback.bot, key, callback.message.chat.id))
    await callback.answer()
