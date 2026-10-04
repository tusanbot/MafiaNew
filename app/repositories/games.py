from datetime import datetime, timezone
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Game, GamePlayer, Group, GroupSettings, Scenario, User


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
    async def get_draft(session: AsyncSession, group_id: int, host_user_id: int | None = None) -> Game | None:
        # A draft belongs to the group, not to the current host selection.
        # The host can be changed while configuring the same draft.
        result = await session.execute(
            select(Game)
            .where(Game.group_id == group_id, Game.status == "draft")
            .order_by(Game.id.desc())
        )
        return result.scalars().first()

    @staticmethod
    async def delete_drafts(session: AsyncSession, group_id: int) -> int:
        """Remove abandoned configuration drafts before starting a fresh flow."""
        result = await session.execute(
            select(Game.id).where(Game.group_id == group_id, Game.status == "draft")
        )
        ids = [row[0] for row in result.all()]
        if not ids:
            return 0
        await session.execute(
            Game.__table__.delete().where(Game.id.in_(ids))
        )
        await session.commit()
        return len(ids)

    @staticmethod
    async def get_by_key(session: AsyncSession, game_key: str) -> Game | None:
        result = await session.execute(select(Game).where(Game.game_key == game_key))
        return result.scalar_one_or_none()

    @staticmethod
    async def create(
        session: AsyncSession,
        group: Group,
        scenario: Scenario,
        host: User,
        game_key: str,
        status: str = "waiting",
        *,
        auto_play: bool = False,
        turn_color: str = "پیش‌فرض",
        challenge_color: str = "پیش‌فرض",
        reserve_enabled: bool = True,
        turn_seconds: int = 120,
        challenge_seconds: int = 60,
        extra_challenge_seconds: int = 60,
    ) -> Game:
        """Create a Game using only settings that are part of the Game schema."""
        game = Game(
            game_key=game_key,
            group_id=group.id,
            scenario_id=scenario.id,
            host_user_id=host.id,
            status=status,
            phase="lobby",
            auto_play=auto_play,
            turn_color=turn_color,
            challenge_color=challenge_color,
            reserve_enabled=reserve_enabled,
            challenge_enabled=True,
            challenge_mode=scenario.challenge_mode,
            challenge_limit=getattr(scenario, "challenge_limit", 1),
            turn_seconds=turn_seconds,
            challenge_seconds=challenge_seconds,
            extra_challenge_seconds=extra_challenge_seconds,
        )
        session.add(game)
        await session.commit()
        await session.refresh(game)
        return game

    @staticmethod
    async def players(session: AsyncSession, game_id: int, include_reserve: bool = False) -> list[tuple[GamePlayer, User]]:
        query = (
            select(GamePlayer, User)
            .join(User, User.id == GamePlayer.user_id)
            .where(GamePlayer.game_id == game_id)
            .order_by(GamePlayer.is_reserved, GamePlayer.seat, GamePlayer.reserve_position)
        )
        if not include_reserve:
            query = query.where(GamePlayer.is_reserved.is_(False))
        result = await session.execute(query)
        return list(result.all())

    @staticmethod
    async def reserves(session: AsyncSession, game_id: int) -> list[tuple[GamePlayer, User]]:
        result = await session.execute(
            select(GamePlayer, User)
            .join(User, User.id == GamePlayer.user_id)
            .where(
                GamePlayer.game_id == game_id,
                GamePlayer.is_reserved.is_(True),
                GamePlayer.is_substitute.is_(False),
            )
            .order_by(GamePlayer.reserve_position)
        )
        return list(result.all())

    @staticmethod
    async def substitutes(session: AsyncSession, game_id: int) -> list[tuple[GamePlayer, User]]:
        result = await session.execute(
            select(GamePlayer, User)
            .join(User, User.id == GamePlayer.user_id)
            .where(GamePlayer.game_id == game_id, GamePlayer.is_substitute.is_(True))
            .order_by(GamePlayer.substitute_position)
        )
        return list(result.all())

    @staticmethod
    async def join_substitute(session: AsyncSession, game: Game, user: User) -> GamePlayer | None:
        if game.status not in ("waiting", "running"):
            return None
        settings = await session.scalar(select(GroupSettings).where(GroupSettings.group_id == game.group_id))
        if settings is not None and not settings.allow_substitute_queue:
            return None
        existing = await session.scalar(select(GamePlayer).where(
            GamePlayer.game_id == game.id, GamePlayer.user_id == user.id
        ))
        if existing:
            return existing if existing.is_substitute else None
        last = await session.scalar(
            select(GamePlayer.substitute_position)
            .where(GamePlayer.game_id == game.id, GamePlayer.is_substitute.is_(True))
            .order_by(GamePlayer.substitute_position.desc())
        )
        player = GamePlayer(
            game_id=game.id, user_id=user.id, seat=0,
            is_reserved=True, is_substitute=True,
            substitute_position=(last or 0) + 1,
        )
        session.add(player)
        await session.commit()
        await session.refresh(player)
        return player

    @staticmethod
    async def join(session: AsyncSession, game: Game, user: User) -> GamePlayer | None:
        if game.status != "waiting":
            return None
        settings = await session.scalar(select(GroupSettings).where(GroupSettings.group_id == game.group_id))
        if settings is not None and not settings.allow_player_join:
            return None
        existing = await session.execute(
            select(GamePlayer).where(GamePlayer.game_id == game.id, GamePlayer.user_id == user.id)
        )
        old = existing.scalar_one_or_none()
        if old is not None:
            # Joining twice is idempotent: return the existing record.
            return old
        scenario = await session.get(Scenario, game.scenario_id)
        if scenario is None:
            return None
        result = await session.execute(
            select(GamePlayer).where(GamePlayer.game_id == game.id, GamePlayer.is_reserved.is_(False))
        )
        players = list(result.scalars())
        if len(players) >= scenario.max_players:
            return None
        used_seats = {player.seat for player in players}
        seat = next((n for n in range(1, scenario.max_players + 1) if n not in used_seats), None)
        if seat is None:
            return None
        player = GamePlayer(game_id=game.id, user_id=user.id, seat=seat, is_reserved=False)
        session.add(player)
        await session.commit()
        await session.refresh(player)
        return player

    @staticmethod
    async def join_at_seat(session: AsyncSession, game: Game, user: User, seat: int) -> GamePlayer | None:
        """Join directly into the requested seat, or move the user's existing seat."""
        if game.status != "waiting":
            return None
        scenario = await session.get(Scenario, game.scenario_id)
        if scenario is None or seat < 1 or seat > scenario.max_players:
            return None
        existing_result = await session.execute(
            select(GamePlayer).where(GamePlayer.game_id == game.id, GamePlayer.user_id == user.id)
        )
        existing = existing_result.scalar_one_or_none()
        occupied_result = await session.execute(
            select(GamePlayer).where(
                GamePlayer.game_id == game.id,
                GamePlayer.is_reserved.is_(False),
                GamePlayer.seat == seat,
            )
        )
        occupied = occupied_result.scalar_one_or_none()
        if existing is not None:
            if existing.is_reserved:
                return None
            if existing.seat == seat:
                return existing
            if occupied is not None and occupied.user_id != user.id:
                return None
            existing.seat = seat
            await session.commit()
            return existing
        if occupied is not None:
            return None
        count_result = await session.execute(
            select(GamePlayer).where(GamePlayer.game_id == game.id, GamePlayer.is_reserved.is_(False))
        )
        if len(list(count_result.scalars())) >= scenario.max_players:
            return None
        player = GamePlayer(game_id=game.id, user_id=user.id, seat=seat, is_reserved=False)
        session.add(player)
        await session.commit()
        await session.refresh(player)
        return player

    @staticmethod
    async def leave(session: AsyncSession, game: Game, user: User) -> tuple[bool, GamePlayer | None]:
        if game.status != "waiting":
            return False, None
        result = await session.execute(
            select(GamePlayer).where(GamePlayer.game_id == game.id, GamePlayer.user_id == user.id)
        )
        player = result.scalar_one_or_none()
        if player is None:
            return False, None
        was_reserved = player.is_reserved
        await session.delete(player)
        await session.flush()

        promoted = None
        if not was_reserved:
            reserve_result = await session.execute(
                select(GamePlayer)
                .where(GamePlayer.game_id == game.id, GamePlayer.is_reserved.is_(True))
                .order_by(GamePlayer.reserve_position)
                .limit(1)
            )
            promoted = reserve_result.scalar_one_or_none()
            if promoted:
                promoted.is_reserved = False
                promoted.reserve_position = None
                promoted.seat = player.seat
                await session.execute(
                    update(GamePlayer)
                    .where(GamePlayer.game_id == game.id, GamePlayer.is_reserved.is_(True))
                    .values(reserve_position=GamePlayer.reserve_position - 1)
                )
        else:
            await session.execute(
                update(GamePlayer)
                .where(GamePlayer.game_id == game.id, GamePlayer.is_reserved.is_(True), GamePlayer.reserve_position > player.reserve_position)
                .values(reserve_position=GamePlayer.reserve_position - 1)
            )
        await session.commit()
        return True, promoted

    @staticmethod
    async def join_reserve(session: AsyncSession, game: Game, user: User) -> GamePlayer | None:
        if game.status != "waiting" or not game.reserve_enabled:
            return None
        settings = await session.scalar(select(GroupSettings).where(GroupSettings.group_id == game.group_id))
        if settings is not None and not settings.allow_reserve_queue:
            return None
        existing = await session.execute(
            select(GamePlayer).where(GamePlayer.game_id == game.id, GamePlayer.user_id == user.id)
        )
        player = existing.scalar_one_or_none()
        if player is not None:
            return player if player.is_reserved else None
        scenario = await session.get(Scenario, game.scenario_id)
        if scenario is None:
            return None
        count_result = await session.execute(
            select(GamePlayer).where(GamePlayer.game_id == game.id, GamePlayer.is_reserved.is_(False))
        )
        if len(list(count_result.scalars())) < scenario.max_players:
            return None
        last_result = await session.execute(
            select(GamePlayer.reserve_position)
            .where(GamePlayer.game_id == game.id, GamePlayer.is_reserved.is_(True))
            .order_by(GamePlayer.reserve_position.desc())
        )
        last = last_result.scalar_one_or_none()
        player = GamePlayer(
            game_id=game.id,
            user_id=user.id,
            seat=0,
            is_reserved=True,
            reserve_position=(last or 0) + 1,
        )
        session.add(player)
        await session.commit()
        await session.refresh(player)
        return player

    @staticmethod
    async def change_seat(session: AsyncSession, game: Game, user: User, seat: int) -> bool:
        if game.status != "waiting":
            return False
        scenario = await session.get(Scenario, game.scenario_id)
        if scenario is None or seat < 1 or seat > scenario.max_players:
            return False
        result = await session.execute(
            select(GamePlayer).where(GamePlayer.game_id == game.id, GamePlayer.user_id == user.id)
        )
        player = result.scalar_one_or_none()
        if player is None or player.is_reserved:
            return False
        target = await session.execute(
            select(GamePlayer).where(GamePlayer.game_id == game.id, GamePlayer.is_reserved.is_(False), GamePlayer.seat == seat)
        )
        occupied = target.scalar_one_or_none()
        if occupied is not None:
            return False
        player.seat = seat
        await session.commit()
        return True

    @staticmethod
    async def reserve(session: AsyncSession, game: Game, user: User) -> bool:
        if game.status != "waiting" or not game.reserve_enabled:
            return False
        result = await session.execute(
            select(GamePlayer).where(GamePlayer.game_id == game.id, GamePlayer.user_id == user.id)
        )
        player = result.scalar_one_or_none()
        if player is None:
            return False
        if player.is_reserved:
            return True
        scenario = await session.get(Scenario, game.scenario_id)
        count_result = await session.execute(
            select(GamePlayer).where(GamePlayer.game_id == game.id, GamePlayer.is_reserved.is_(False))
        )
        if scenario is None or len(list(count_result.scalars())) < scenario.max_players:
            return False
        last_result = await session.execute(
            select(GamePlayer.reserve_position)
            .where(GamePlayer.game_id == game.id, GamePlayer.is_reserved.is_(True))
            .order_by(GamePlayer.reserve_position.desc())
        )
        last = last_result.scalar_one_or_none()
        player.is_reserved = True
        player.reserve_position = (last or 0) + 1
        player.seat = 0
        await session.commit()
        return True

    @staticmethod
    async def replace_player(session: AsyncSession, game: Game, source: GamePlayer, destination: GamePlayer) -> bool:
        if game.status not in ("waiting", "running"):
            return False
        if not source.is_substitute or not destination.alive or destination.is_reserved:
            return False
        old_sub_position = source.substitute_position
        replacement_user_id = source.user_id
        # The substitute row currently owns the same (game_id, user_id)
        # identity that we are about to assign to the destination row. Delete
        # and flush it first; otherwise PostgreSQL can hit the unique
        # constraint before SQLAlchemy orders the DELETE ahead of the UPDATE.
        await session.delete(source)
        await session.flush()

        # The destination seat/role is preserved. Only the user occupying that
        # seat is replaced. This works identically for lobby and running games.
        destination.user_id = replacement_user_id
        destination.is_reserved = False
        destination.is_substitute = False
        destination.reserve_position = None
        destination.substitute_position = None
        destination.alive = True
        destination.exit_type = None
        destination.warning_count = 0
        await session.flush()
        if old_sub_position is not None:
            await session.execute(update(GamePlayer).where(
                GamePlayer.game_id == game.id,
                GamePlayer.is_substitute.is_(True),
                GamePlayer.substitute_position > old_sub_position,
            ).values(substitute_position=GamePlayer.substitute_position - 1))
        await session.commit()
        return True

    @staticmethod
    async def change_scenario_seats(session: AsyncSession, game: Game, scenario: Scenario) -> dict:
        """Switch a waiting game's scenario while preserving existing seat numbers when possible."""
        if game.status != "waiting":
            raise ValueError("تغییر سناریو فقط در لابی امکان‌پذیر است.")

        rows = await GameRepository.players(session, game.id, include_reserve=True)
        active = [(p, u) for p, u in rows if not p.is_reserved]
        reserves = [(p, u) for p, u in rows if p.is_reserved]
        snapshot = [(p, u, int(p.seat)) for p, u in active]

        kept = [(p, u, seat) for p, u, seat in snapshot if 1 <= seat <= int(scenario.max_players)]
        overflow = [(p, u, seat) for p, u, seat in snapshot if seat > int(scenario.max_players) or seat < 1]
        used = {seat for _, _, seat in kept}
        free = [seat for seat in range(1, int(scenario.max_players) + 1) if seat not in used]

        # Avoid the unique (game_id, seat) constraint while remapping.
        for p, _, _ in snapshot:
            p.seat = -int(p.id)
        await session.flush()

        for p, _, old_seat in kept:
            p.is_reserved = False
            p.reserve_position = None
            p.seat = old_seat

        free_iter = iter(free)
        for p, _, _ in overflow:
            try:
                p.is_reserved = False
                p.reserve_position = None
                p.seat = next(free_iter)
            except StopIteration:
                p.is_reserved = True
                p.seat = 0
                p.reserve_position = None

        # Existing reserves keep their order; newly overflowed players are appended.
        reserve_players = [(p, u) for p, u in reserves if p.is_reserved]
        newly_reserved = [(p, u) for p, u, _ in overflow if p.is_reserved]
        reserve_players.extend(newly_reserved)
        for position, (p, _) in enumerate(reserve_players, 1):
            p.is_reserved = True
            p.seat = 0
            p.reserve_position = position

        game.scenario_id = scenario.id
        await session.commit()
        return {
            "active_count": len(snapshot) - len(newly_reserved),
            "reserve_count": len(reserve_players),
        }

    @staticmethod
    async def mark_removed(session: AsyncSession, player: GamePlayer, exit_type: str) -> None:
        player.alive = False
        player.exit_type = exit_type
        await session.commit()

    @staticmethod
    async def restore_player(session: AsyncSession, player: GamePlayer) -> bool:
        if player.alive or player.exit_type != "death":
            return False
        player.alive = True
        player.exit_type = None
        player.silence_until_round = None
        player.extra_turn_round = None
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
