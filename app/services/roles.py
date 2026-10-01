import secrets
from collections import Counter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Game, GamePlayer, Role, Scenario, User

def build_role_keys(player_count: int) -> list[str]:
    if player_count < 7:
        raise ValueError("حداقل ۷ بازیکن لازم است.")
    mafia_count = max(2, player_count // 4)
    keys = ["godfather"] + ["mafia"] * (mafia_count - 1)
    citizen_specials = ["doctor", "detective"]
    keys.extend(citizen_specials)
    keys.extend(["citizen"] * max(0, player_count - len(keys)))
    if len(keys) != player_count:
        raise ValueError("ترکیب نقش‌ها با تعداد بازیکنان سازگار نیست.")
    return keys

async def assign_roles(session: AsyncSession, game: Game) -> list[tuple[GamePlayer, Role, User]]:
    result = await session.execute(
        select(GamePlayer, User)
        .join(User, User.id == GamePlayer.user_id)
        .where(GamePlayer.game_id == game.id)
        .order_by(GamePlayer.seat)
    )
    players = list(result.all())
    keys = build_role_keys(len(players))
    secrets.SystemRandom().shuffle(keys)

    roles_result = await session.execute(select(Role).where(Role.key.in_(set(keys))))
    role_map = {role.key: role for role in roles_result.scalars()}
    if len(role_map) != len(set(keys)):
        missing = set(keys) - set(role_map)
        raise ValueError(f"نقش‌های ثبت نشده: {', '.join(sorted(missing))}")

    assigned = []
    for (player, user), key in zip(players, keys):
        role = role_map[key]
        player.role_id = role.id
        player.alive = True
        assigned.append((player, role, user))
    await session.commit()
    return assigned

def role_distribution_summary(assignments):
    return Counter(role.key for _, role, _ in assignments)
