from aiogram import Router
from aiogram.types import CallbackQuery
from sqlalchemy import select

from app.db.models import Game, GamePlayer, Role, User
from app.db.session import session_factory
from app.repositories.games import GameRepository
from app.services.gameplay import start_match, alive_players

router = Router(name="gameplay")

async def _load(session, key):
    return await GameRepository.get_by_key(session, key)

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
        scenario = await session.get(__import__("app.db.models", fromlist=["Scenario"]).Scenario, game.scenario_id)
        if not scenario or len(players) < scenario.min_players:
            await callback.answer("تعداد بازیکنان کافی نیست.", show_alert=True)
            return
        try:
            assignments = await start_match(session, game)
        except ValueError as exc:
            await callback.answer(str(exc), show_alert=True)
            return
        await callback.message.edit_text(
            f"بازی {game.game_key} شروع شد.
"
            f"سناریو: {scenario.name_fa}
"
            f"بازیکنان: {len(assignments)}

"
            "نقش‌ها به‌صورت خصوصی ارسال شدند.
"
            "شب اول آغاز شد."
        )
        for _, role, user in assignments:
            try:
                await callback.bot.send_message(
                    user.telegram_id,
                    f"نقش شما در بازی {game.game_key}

"
                    f"نقش: {role.name_fa}
"
                    f"تیم: {role.team}

"
                    f"{role.description}",
                )
            except Exception:
                pass
        await callback.answer("بازی شروع شد و نقش‌ها ارسال شدند.")
