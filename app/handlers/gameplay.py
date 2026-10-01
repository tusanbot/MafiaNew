from aiogram import Router
from aiogram.types import CallbackQuery
from sqlalchemy import select
import json
import asyncio

from app.db.models import Game, Group, User, Scenario, GameEvent
from app.db.session import session_factory
from app.repositories.games import GameRepository
from app.services.gameplay import (
    alive_players,
    current_round,
    resolve_night,
    start_match,
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
)
from app.handlers.keyboards import (
    day_keyboard,
    night_action_keyboard,
    vote_keyboard,
    day_turn_keyboard,
    challenge_requests_keyboard,
    challenge_placement_keyboard,
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
TURN_SECONDS = 60

async def _load(session, key):
    return await GameRepository.get_by_key(session, key)

async def _schedule_auto_next(bot, game_key: str):
    async def runner():
        await asyncio.sleep(TURN_SECONDS)
        async with session_factory() as session:
            game = await _load(session, game_key)
            if not game or game.status != "running" or not game.next_auto_enabled:
                return
            turn = await current_turn(session, game.id)
            if not turn or turn.get("status") != "active":
                return
            chat_id = await _group_chat_id(session, game)
            try:
                result = await next_turn(session, game)
            except ValueError:
                return
            if not chat_id:
                return
            if result["kind"] == "finished_day":
                await bot.send_message(chat_id, "زمان نوبت به پایان رسید و صحبت‌های این دور تمام شد.", reply_markup=day_keyboard(game.game_key, await alive_players(session, game.id)))
            else:
                user = await session.get(User, result["user_id"])
                name = user.display_name or user.first_name if user else "بازیکن"
                kind = "چالش" if result["kind"] == "challenge" else "اصلی"
                await bot.send_message(chat_id, f"زمان نوبت تمام شد؛ نوبت {kind} {name} شروع شد.", reply_markup=_day_keyboard(game, True))
                if game.next_auto_enabled:
                    _turn_tasks[game.id] = asyncio.create_task(_schedule_auto_next(bot, game_key))
    old = _turn_tasks.pop(game.id, None)
    if old:
        old.cancel()
    _turn_tasks[game.id] = asyncio.create_task(runner())


async def _group_chat_id(session, game):
    group = await session.get(Group, game.group_id)
    return group.telegram_id if group else None

async def _send_night_menus(bot, session, game):
    players = await alive_players(session, game.id)
    for player, user, role in players:
        if not role or role.key not in {"godfather", "mafia", "doctor", "detective"}:
            continue
        action = "mafia_kill" if role.team == "mafia" else f"{role.key}_{'save' if role.key == 'doctor' else 'check'}"
        try:
            await bot.send_message(
                user.telegram_id,
                f"شب بازی {game.game_key}\n\nنقش: {role.name_fa}\nاقدام خود را انتخاب کن:",
                reply_markup=night_action_keyboard(game.game_key, action, players),
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
            f"بازی {game.game_key} شروع شد.\nسناریو: {scenario.name_fa}\nبازیکنان: {len(assignments)}"
            "نقش‌ها خصوصی ارسال شدند. شب اول آغاز شد."
        )
        for _, role, user in assignments:
            try:
                await callback.bot.send_message(
                    user.telegram_id,
                    f"نقش شما در بازی {game.game_key}\n\nنقش: {role.name_fa}\nتیم: {role.team}\n\n{role.description}",
                )
            except Exception:
                pass
        await _send_night_menus(callback.bot, session, game)
        await callback.answer("بازی شروع شد.")

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
            if result["winner"]:
                text = f"بازی تمام شد. تیم {('مافیا' if result['winner']=='mafia' else 'شهروند')} برنده شد."
            elif result["eliminated"]:
                text = f"روز آغاز شد.\nبازیکن {result['eliminated'].display_name} در شب حذف شد."
            else:
                text = "روز آغاز شد.\nاین شب حذف نداشت."
            if chat_id:
                if not result["winner"]:
                    await start_day_turns(session, game)
                    if game.next_auto_enabled:
                        await _schedule_auto_next(callback.bot, game.game_key)
                    turn = await current_turn(session, game.id)
                    speaker = await session.get(User, int(turn["user_id"])) if turn else None
                    name = speaker.display_name or speaker.first_name if speaker else "بازیکن"
                    await callback.bot.send_message(chat_id, text + f"\n\nنوبت اصلی: {name}", reply_markup=_day_keyboard(game, True))
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
                    await callback.bot.send_message(chat_id, text + f"\n\nنوبت اصلی: {name}", reply_markup=day_turn_keyboard(game.game_key, True))
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
            f"درخواست چالش: {actor.display_name or actor.first_name}\n"
            f"صاحب ترن اصلی: {turn_owner.display_name or turn_owner.first_name}\n\n"
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
                            f"چالش به {name} داده شد.\n\nزمان اجرا را انتخاب کنید:",
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
        chat_id = await _group_chat_id(session, game)
        requester = await session.get(User, result["requester_id"])
        if chat_id and requester:
            await callback.bot.send_message(chat_id, f"{actor.display_name or actor.first_name} به {requester.display_name or requester.first_name} چالش داد. زمان اجرای چالش در حال تعیین است.")
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
                            f"زمان انتخاب نشد؛ چالش {req.display_name or req.first_name} بعد از صحبت اجرا می‌شود.",
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
            f"چالش {name}: {'قبل از صحبت' if result['placement'] == 'before' else 'بعد از صحبت'} انتخاب شد."
        )
        if chat_id:
            if result["placement"] == "before":
                await callback.bot.send_message(
                chat_id,
                f"چالش {name} قبل از ادامه صحبت اجرا می‌شود.",
                reply_markup=day_turn_keyboard(
                    game.game_key, True, game.challenge_enabled,
                    game.turn_color_enabled, game.turn_color, game.challenge_color,
                    True, False
                ),
            )
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
        if result["kind"] == "finished_day":
            old_task = _turn_tasks.pop(game.id, None)
            if old_task:
                old_task.cancel()

            await callback.bot.send_message(
                chat_id,
                "نوبت‌های اصلی این دور تمام شد. اکنون رأی‌گیری را می‌توانید شروع کنید.",
                reply_markup=day_keyboard(game.game_key, await alive_players(session, game.id)),
            )
        else:
            user = await session.get(User, result["user_id"])
            name = user.display_name or user.first_name if user else "بازیکن"
            kind = "چالش" if result["kind"] == "challenge" else "اصلی"
            await callback.bot.send_message(
                chat_id,
                f"نوبت {kind} {name} شروع شد.",
                reply_markup=day_turn_keyboard(
                    game.game_key, True, game.challenge_enabled,
                    game.turn_color_enabled, game.turn_color, game.challenge_color,
                    True, result["kind"] != "extra"
                ),
            )
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
            await callback.bot.send_message(chat_id, "🌙 فاز شب آغاز شد.")
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
        await callback.message.edit_text("🏁 بازی توسط گرداننده به پایان رسید. نتیجه: بدون برنده.")
        await callback.answer("بازی تمام شد.")

@router.callback_query(lambda c: c.data and c.data.startswith("day:vote:"))
async def day_vote_handler(callback: CallbackQuery):
    key = callback.data.split(":", 2)[2]
    async with session_factory() as session:
        game = await _load(session, key)
        if not game:
            await callback.answer("بازی پیدا نشد.", show_alert=True)
            return
        try:
            await start_voting(session, game)
        except ValueError as exc:
            await callback.answer(str(exc), show_alert=True)
            return
        players = await alive_players(session, game.id)
        await callback.message.edit_text(
            f"رأی‌گیری دور {await current_round(session, game.id)}\n\nهدف را انتخاب کنید:",
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
            await callback.message.edit_text(
                f"بازی تمام شد. تیم {('مافیا' if result['winner']=='mafia' else 'شهروند')} برنده شد."
            )
        else:
            if result["eliminated"]:
                text = f"رأی‌گیری تمام شد. {result['eliminated'].display_name} حذف شد."
            else:
                text = "رأی‌گیری مساوی شد و کسی حذف نشد."
            await callback.message.edit_text(text + "\n\nشب بعد آغاز شد.")
            await _send_night_menus(callback.bot, session, game)
        await callback.answer("رأی ثبت شد.")
