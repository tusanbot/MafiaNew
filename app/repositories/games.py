from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Game, GamePlayer, Group, Scenario, User

class GameRepository:
    @staticmethod
    async def get_active(session: AsyncSession, group_id: int) -> Game | None:
        result = await session.execute(
            select(Game)
            .where(Game.group_id == group_id, Game.status.in_(("waiting", "running")))
            .order_by(Game.id.desc())
        )
        return result.scalars().first()

    @staticmethod
    async def get_by_key(session: AsyncSession, game_key: str) -> Game | None:
        result = await session.execute(select(Game).where(Game.game_key == game_key))
        return result.scalar_one_or_none()

    @staticmethod
    async def create(session: AsyncSession, group: Group, scenario: Scenario, host: User, game_key: str) -> Game:
        game = Game(
            game_key=game_key,
            group_id=group.id,
            scenario_id=scenario.id,
            host_user_id=host.id,
            status="waiting",
            phase="lobby",
        )
        session.add(game)
        await session.commit()
        await session.refresh(game)
        return game

    @staticmethod
    async def players(session: AsyncSession, game_id: int) -> list[tuple[GamePlayer, User]]:
        result = await session.execute(
            select(GamePlayer, User)
            .join(User, User.id == GamePlayer.user_id)
            .where(GamePlayer.game_id == game_id)
            .order_by(GamePlayer.seat)
        )
        return list(result.all())

    @staticmethod
    async def join(session: AsyncSession, game: Game, user: User) -> GamePlayer | None:
        if game.status != "waiting":
            return None
        existing = await session.execute(
            select(GamePlayer).where(GamePlayer.game_id == game.id, GamePlayer.user_id == user.id)
        )
        if existing.scalar_one_or_none() is not None:
            return None
        scenario = await session.get(Scenario, game.scenario_id)
        if scenario is None:
            return None
        result = await session.execute(select(GamePlayer).where(GamePlayer.game_id == game.id))
        players = list(result.scalars())
        if len(players) >= scenario.max_players:
            return None
        used_seats = {player.seat for player in players}
        seat = next((n for n in range(1, scenario.max_players + 1) if n not in used_seats), None)
        if seat is None:
            return None
        player = GamePlayer(game_id=game.id, user_id=user.id, seat=seat)
        session.add(player)
        await session.commit()
        await session.refresh(player)
        return player

    @staticmethod
    async def leave(session: AsyncSession, game: Game, user: User) -> bool:
        if game.status != "waiting":
            return False
        result = await session.execute(
            select(GamePlayer).where(GamePlayer.game_id == game.id, GamePlayer.user_id == user.id)
        )
        player = result.scalar_one_or_none()
        if player is None:
            return False
        await session.delete(player)
        await session.commit()
        return True

    @staticmethod
    async def start(session: AsyncSession, game: Game) -> bool:
        if game.status != "waiting":
            return False
        game.status = "running"
        game.phase = "setup"
        game.started_at = datetime.now(timezone.utc)
        await session.commit()
        return True

    @staticmethod
    async def cancel(session: AsyncSession, game: Game) -> bool:
        if game.status not in ("waiting", "running"):
            return False
        game.status = "cancelled"
        game.phase = "finished"
        game.finished_at = datetime.now(timezone.utc)
        await session.commit()
        return True
