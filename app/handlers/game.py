from aiogram import Router
from aiogram.types import CallbackQuery
from sqlalchemy import select

from app.db.models import Scenario
from app.db.session import session_factory
from app.repositories.games import GameRepository
from app.repositories.groups import GroupRepository
from app.repositories.users import UserRepository
from app.handlers.keyboards import lobby_keyboard

router = Router(name="game")


async def _load_game(session, game_key: str):
    return await GameRepository.get_by_key(session, game_key)


@router.callback_query(lambda c: c.data and c.data.startswith("game:join:"))
async def join_game(callback: CallbackQuery) -> None:
    game_key = callback.data.split(":", 2)[2]
    if not callback.from_user or not callback.message:
        return
    async with session_factory() as session:
        game = await _load_game(session, game_key)
        if not game or game.status != "waiting":
            await callback.answer("این بازی دیگر قابل پیوستن نیست.", show_alert=True)
            return
        user = await UserRepository.upsert_from_telegram(session, callback.from_user)
        player = await GameRepository.join(session, game, user)
        if player is None:
            await callback.answer("امکان پیوستن وجود ندارد؛ شاید قبلاً وارد شده‌اید یا ظرفیت پر است.", show_alert=True)
            return
        players = await GameRepository.players(session, game.id)
        scenario = await session.get(Scenario, game.scenario_id)
        can_start = len(players) >= (scenario.min_players if scenario else 999)
        lines = [f"بازی مافیا — {game.game_key}", "", f"تعداد بازیکنان: {len(players)}"]
        for p in players:
            lines.append(f"صندلی {p.seat}: بازیکن {p.user_id}")
        await callback.message.edit_text(
            "\n".join(lines),
            reply_markup=lobby_keyboard(game.game_key, can_start=can_start),
        )
        await callback.answer("با موفقیت وارد بازی شدی.")


@router.callback_query(lambda c: c.data and c.data.startswith("game:leave:"))
async def leave_game(callback: CallbackQuery) -> None:
    game_key = callback.data.split(":", 2)[2]
    if not callback.from_user or not callback.message:
        return
    async with session_factory() as session:
        game = await _load_game(session, game_key)
        if not game:
            await callback.answer("بازی پیدا نشد.", show_alert=True)
            return
        user = await UserRepository.upsert_from_telegram(session, callback.from_user)
        if not await GameRepository.leave(session, game, user):
            await callback.answer("ترک بازی ممکن نیست.", show_alert=True)
            return
        players = await GameRepository.players(session, game.id)
        scenario = await session.get(Scenario, game.scenario_id)
        can_start = len(players) >= (scenario.min_players if scenario else 999)
        lines = [f"بازی مافیا — {game.game_key}", "", f"تعداد بازیکنان: {len(players)}"]
        for p in players:
            lines.append(f"صندلی {p.seat}: بازیکن {p.user_id}")
        await callback.message.edit_text(
            "\n".join(lines),
            reply_markup=lobby_keyboard(game.game_key, can_start=can_start),
        )
        await callback.answer("از بازی خارج شدی.")


@router.callback_query(lambda c: c.data and c.data.startswith("game:start:"))
async def start_game(callback: CallbackQuery) -> None:
    game_key = callback.data.split(":", 2)[2]
    if not callback.from_user or not callback.message:
        return
    async with session_factory() as session:
        game = await _load_game(session, game_key)
        if not game:
            await callback.answer("بازی پیدا نشد.", show_alert=True)
            return
        players = await GameRepository.players(session, game.id)
        scenario = await session.get(Scenario, game.scenario_id)
        if not scenario or len(players) < scenario.min_players:
            await callback.answer("تعداد بازیکنان برای شروع کافی نیست.", show_alert=True)
            return
        first = players[0] if players else None
        user = await UserRepository.upsert_from_telegram(session, callback.from_user)
        if not first or first.user_id != user.id:
            await callback.answer("فقط سازنده بازی می‌تواند آن را شروع کند.", show_alert=True)
            return
        await GameRepository.start(session, game)
        await callback.message.edit_text(
            f"بازی {game.game_key} شروع شد.\n\nسناریو: {scenario.name_fa}\nتعداد بازیکنان: {len(players)}"
        )
        await callback.answer("بازی شروع شد.")
