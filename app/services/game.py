from uuid import uuid4
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Scenario
from app.repositories.games import GameRepository


async def create_game(session, group, scenario: Scenario):
    key = uuid4().hex[:12]
    return await GameRepository.create(session, group, scenario, key)


async def render_lobby(session: AsyncSession, game) -> str:
    players = await GameRepository.players(session, game.id)
    lines = [f"بازی مافیا — {game.game_key}", "", f"تعداد بازیکنان: {len(players)}"]
    for player in players:
        lines.append(f"صندلی {player.seat}: بازیکن {player.user_id}")
    lines.append("")
    lines.append("برای پیوستن یا ترک بازی از دکمه‌های زیر استفاده کنید.")
    return "\n".join(lines)
