from aiogram import Router
from aiogram.types import CallbackQuery
from sqlalchemy import select

from app.db.models import Game, Group, User, Scenario
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
)
from app.handlers.keyboards import (
    day_keyboard,
    night_action_keyboard,
    vote_keyboard,
)

router = Router(name="gameplay")

async def _load(session, key):
    return await GameRepository.get_by_key(session, key)

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
    if len(parts) != 3 or not callback.from_user:
        return
    action, key, target = parts
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
                await callback.bot.send_message(chat_id, text, reply_markup=day_keyboard(game.game_key) if not result["winner"] else None)
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
                await callback.bot.send_message(chat_id, text, reply_markup=day_keyboard(game.game_key) if not resolved["winner"] else None)
        await callback.answer("اقدام شب ثبت شد.")

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
            text = f"بازی تمام شد. تیم {('مافیا' if result['winner']=='mafia' else 'شهروند')} برنده شد."
            await callback.message.edit_text(text)
        else:
            if result["eliminated"]:
                text = f"رأی‌گیری تمام شد. {result['eliminated'].display_name} حذف شد."
            else:
                text = "رأی‌گیری مساوی شد و کسی حذف نشد."
            await callback.message.edit_text(text + "\n\nشب بعد آغاز شد.")
            await _send_night_menus(callback.bot, session, game)
        await callback.answer("رأی ثبت شد.")
