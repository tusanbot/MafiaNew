from uuid import uuid4
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Scenario, User
from app.repositories.games import GameRepository

async def create_game(session: AsyncSession, group, scenario: Scenario, host: User):
    key = uuid4().hex[:12]
    return await GameRepository.create(session, group, scenario, host, key)

async def render_lobby(session: AsyncSession, game) -> tuple[str, int]:
    players = await GameRepository.players(session, game.id)
    scenario = await session.get(Scenario, game.scenario_id)
    min_players = scenario.min_players if scenario else 999
    max_players = scenario.max_players if scenario else 0
    lines = [
        f"بازی مافیا — {game.game_key}",
        f"سناریو: {scenario.name_fa if scenario else 'نامشخص'}",
        f"بازیکنان: {len(players)}/{max_players}",
        "",
    ]
    for player, user in players:
        lines.append(f"صندلی {player.seat}: {user.display_name or user.telegram_id}")
    lines.extend(["", f"حداقل برای شروع: {min_players}", "برای ورود یا خروج از دکمه‌های زیر استفاده کنید."])
    return "\n".join(lines), len(players) >= min_players
