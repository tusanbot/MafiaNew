import secrets
from collections import Counter
import json
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import Game, GamePlayer, Role, Scenario, ScenarioRole, User

def build_role_keys(player_count: int, scenario: Scenario | None = None) -> list[str]:
    if scenario and scenario.key:
        # Legacy scenarios store the exact seat-by-seat role list in the registry.
        from app.scenarios.legacy import get_scenario
        definition = get_scenario(scenario.key)
        if definition and len(definition.role_keys) == player_count:
            return list(definition.role_keys)
    if player_count < 7:
        raise ValueError("حداقل ۷ بازیکن لازم است.")
    mafia_count = max(2, player_count // 4)
    keys = ["godfather"] + ["mafia"] * (mafia_count - 1) + ["doctor", "detective"]
    keys.extend(["citizen"] * max(0, player_count - len(keys)))
    if len(keys) != player_count:
        raise ValueError("ترکیب نقش‌ها با تعداد بازیکنان سازگار نیست.")
    return keys

async def assign_roles(session: AsyncSession, game: Game) -> list[tuple[GamePlayer, Role, User]]:
    result = await session.execute(select(GamePlayer, User).join(User, User.id == GamePlayer.user_id).where(GamePlayer.game_id == game.id).order_by(GamePlayer.seat))
    players = list(result.all())
    scenario = await session.get(Scenario, game.scenario_id)
    composition = list((await session.execute(
        select(ScenarioRole, Role)
        .join(Role, Role.id == ScenarioRole.role_id)
        .where(ScenarioRole.scenario_id == game.scenario_id)
        .order_by(ScenarioRole.position, ScenarioRole.id)
    )).all())
    if composition:
        keys = []
        for scenario_role, role in composition:
            keys.extend([role.key] * max(1, scenario_role.count))
        if len(keys) != len(players):
            raise ValueError(f"تعداد نقش‌های سناریو ({len(keys)}) با تعداد بازیکنان ({len(players)}) برابر نیست.")
    else:
        keys = build_role_keys(len(players), scenario)
    secrets.SystemRandom().shuffle(keys)
    roles_result = await session.execute(select(Role).where(Role.key.in_(set(keys))))
    role_map = {role.key: role for role in roles_result.scalars()}
    if len(role_map) != len(set(keys)):
        missing = set(keys) - set(role_map)
        raise ValueError(f"نقش‌های ثبت نشده: {', '.join(sorted(missing))}")
    assigned=[]
    for (player,user),key in zip(players,keys):
        role=role_map[key]
        player.role_id=role.id
        player.alive=True
        player.exit_type=None
        assigned.append((player,role,user))
    await session.flush()
    return assigned

def role_distribution_summary(assignments):
    return Counter(role.key for _, role, _ in assignments)
