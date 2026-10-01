from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.models import Game, GamePlayer, Role, User
from app.core.game.engine import GameEngine, GameEnginePhase, GameState
from app.services.roles import assign_roles

async def start_match(session: AsyncSession, game: Game):
    assignments = await assign_roles(session, game)
    game.status = "running"
    game.phase = GameEnginePhase.NIGHT.value
    await session.commit()
    return assignments

async def alive_players(session: AsyncSession, game_id: int):
    result = await session.execute(
        select(GamePlayer, User, Role)
        .join(User, User.id == GamePlayer.user_id)
        .outerjoin(Role, Role.id == GamePlayer.role_id)
        .where(GamePlayer.game_id == game_id, GamePlayer.alive.is_(True))
        .order_by(GamePlayer.seat)
    )
    return list(result.all())

async def set_phase(session: AsyncSession, game: Game, target: GameEnginePhase):
    state = GameState(GameEnginePhase(game.phase), 1)
    GameEngine.transition(state, target)
    game.phase = target.value
    await session.commit()

def check_winner(assignments_or_players):
    teams = {role.team for _, role, _ in assignments_or_players if getattr(_, "alive", True)}
    mafia_alive = any(role.team == "mafia" and getattr(player, "alive", True) for player, role, _ in assignments_or_players)
    citizens_alive = any(role.team == "citizen" and getattr(player, "alive", True) for player, role, _ in assignments_or_players)
    if not mafia_alive:
        return "citizen"
    if not citizens_alive:
        return "mafia"
    return None
