from aiogram import Router
from aiogram.types import CallbackQuery
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
    submit_vote,
    resolve_challenge,
    start_day_turns,
    start_new_day_round,
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
    """Turn messages are immutable history except for their final state."""
    event, data = await _turn_message(session, game, turn)
    if not event or not data:
        return
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
    text = (f"🗣 نوبت صحبت {tg_name(raw_name)}\n\n"
            f"⏱ {_duration_text(_turn_duration(game, kind))}{request_section}")
    msg = await bot.send_message(
        chat_id, text,
        reply_markup=day_turn_keyboard(game.game_key, True, game.challenge_enabled, game.turn_color_enabled,
                                       game.turn_color, game.challenge_color, True, kind not in {"extra", "challenge"}, requests),
        parse_mode="HTML",
    )
    await _register_turn_message(session, game, chat_id=chat_id, message_id=msg.message_id, turn=turn)
    return msg


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
    text = f"🗣 نوبت صحبت {tg_name(raw_name)}\n\n⏱ {_duration_text(_turn_duration(game, kind))}{request_section}"
    try:
        await bot.edit_message_text(text, chat_id=int(data["chat_id"]), message_id=int(data["message_id"]),
                                    reply_markup=day_turn_keyboard(game.game_key, True, game.challenge_enabled, game.turn_color_enabled,
                                                                   game.turn_color, game.challenge_color, True, kind not in {"extra", "challenge"}, requests),
                                    parse_mode="HTML")
    except Exception:
        pass

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
                        # Keep the finished turn as history; the voting prompt is separate.
                        try:
                            await bot.send_message(
                                chat_id,
                                "🗳 نوبت‌های این دور تمام شد. آماده رأی‌گیری هستید.",
                                reply_markup=day_keyboard(
                                    game.game_key,
                                    await alive_players(session, game.id),
                                ),
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


async def _public_status_roster(session, game) -> str:
    try:
        emoji_settings = json.loads(game.emoji_settings or "{}")
    except (TypeError, ValueError):
        emoji_settings = {}
    rows = await all_players(session, game.id)
    leader_id = None
    leader_event = await session.scalar(
        select(GameEvent).where(
            GameEvent.game_id == game.id,
            GameEvent.event_type == "leader_selected",
        ).order_by(GameEvent.id.desc())
    )
    if leader_event:
        try:
            leader_id = int(json.loads(leader_event.payload or "{}").get("leader_user_id"))
        except (TypeError, ValueError):
            leader_id = None
    lines = ["\u200f👥 <b>لیست بازیکنان حاضر در بازی</b>", ""]
    for player, user, _role in rows:
        if player.is_reserved:
            continue
        raw_name = user.display_name or user.first_name or user.username or "بازیکن"
        name = tg_mention(user.telegram_id, raw_name)
        marks = []
        if user.id == leader_id:
            marks.append("👑")
        if player.alive:
            if player.silence_until_round is not None and emoji_settings.get("silence", True): marks.append("🔇")
            if player.extra_turn_round is not None and emoji_settings.get("extra_turn", True): marks.append("➕")
            if player.warning_count and emoji_settings.get("warning", True): marks.append(f"⚠️{player.warning_count}")
            state = "زنده"
        else:
            if player.exit_type == "death" and emoji_settings.get("death", True): marks.append("💀")
            elif player.exit_type == "kick" and emoji_settings.get("kick", True): marks.append("⛔")
            elif player.exit_type == "slaughter" and emoji_settings.get("slaughter", True): marks.append("🩸")
            state = "حذف‌شده"
        lines.append(f"\u200f{player.seat:02d}. {' '.join(marks)} {name} — {state}".strip())
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
            if not await night_ready(session, game):
                await callback.answer("شب هنوز آماده حل شدن نیست.", show_alert=True)
                return
            await callback.answer("اقدامات شب کامل است؛ برای حل شب «شروع روز» را بزنید.")
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
            await callback.answer("اقدامات شب کامل شد؛ برای حل شب «شروع روز» را بزنید.")
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
        turn = await current_turn(session, game.id)
        turn_event, turn_data = await _turn_message(session, game, turn)
        if turn_event and turn_data:
            try:
                await callback.bot.edit_message_text(
                    f"🗣 نوبت صحبت {tg_name((await session.get(User, int(turn["user_id"]))).display_name)}\n\n"
                    "⚔️ <b>درخواست چالش انتخاب شد.</b>",
                    chat_id=int(turn_data["chat_id"]), message_id=int(turn_data["message_id"]),
                    reply_markup=None, parse_mode="HTML"
                )
            except Exception:
                pass
        chat_id = await _group_chat_id(session, game)
        if chat_id:
            await callback.bot.send_message(
                chat_id,
                f"⚔️ چالش به {tg_name(requester_name)} داده شد.",
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
            f"⚔️ چالش برای {name} تأیید شد.\nزمان اجرا: {'قبل از صحبت' if result['placement'] == 'before' else 'بعد از صحبت'}"
        )
        if chat_id:
            if result["placement"] == "before":
                challenge_turn = await current_turn(session, game.id)
                if challenge_turn:
                    try:
                        await callback.message.edit_text(
                            f"⚔️ چالش برای {name} اجرا شد.\n\nبعد از انتخاب جایگاه، نوبت چالش جداگانه آغاز شد."
                        )
                    except Exception:
                        pass
                    challenge_msg = await _send_turn_message(
                        callback.bot, session, game, chat_id, challenge_turn
                    )
                    if challenge_msg:
                        await _schedule_auto_next(
                            callback.bot, game.game_key, chat_id, challenge_msg.message_id
                        )
            else:
                try:
                    await callback.message.edit_text(
                        f"⚔️ چالش برای {name} تأیید شد.\n\nبعد از پایان نوبت اصلی اجرا می‌شود."
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
                "🗳 نوبت‌های این دور تمام شد. آماده رأی‌گیری هستید.",
                reply_markup=day_keyboard(game.game_key, await alive_players(session, game.id)),
            )
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
        if not turn or turn.get("status") != "finished":
            await callback.answer("ابتدا باید صحبت‌های دور تمام شود.", show_alert=True)
            return
        if game.phase != "day":
            await callback.answer("مرحله روز فعال نیست.", show_alert=True)
            return
        game.phase = "night"
        await session.commit()
        settings = await session.scalar(select(GroupSettings).where(GroupSettings.group_id == game.group_id))
        chat_id = await _group_chat_id(session, game)
        if chat_id:
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
            await callback.message.edit_reply_markup(reply_markup=None)
            await callback.answer("بازی تمام شد.")
            return
        await start_new_day_round(session, game)
        if chat_id:
            await update_round_roster(callback.bot, session, game, chat_id)
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
