from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import Achievement, GameEvent, GamePlayer, Role, User, UserAchievement

ACHIEVEMENTS = (
    ("first_game", "اولین بازی", "اولین بازی کامل‌شده", "🎮", 10),
    ("first_win", "اولین برد", "اولین برد در بازی", "🏆", 20),
    ("ten_games", "بازیکن باتجربه", "تکمیل ۱۰ بازی", "⭐", 30),
    ("ten_wins", "برنده حرفه‌ای", "کسب ۱۰ برد", "🥇", 50),
    ("mafia_master", "مافیای کارکشته", "کسب ۱۰ برد با تیم مافیا", "🔴", 50),
    ("citizen_master", "شهروند کارکشته", "کسب ۱۰ برد با تیم شهروند", "🔵", 50),
    ("independent_master", "مستقل کارکشته", "کسب ۵ برد با تیم مستقل", "🟣", 40),
    ("challenge_10", "چالش‌گر", "ثبت ۱۰ چالش", "⚔️", 25),
    ("challenge_50", "چالش‌گر حرفه‌ای", "ثبت ۵۰ چالش", "🔥", 75),
)

RANKS = (
    (0, "تازه‌وارد"),
    (100, "بازیکن"),
    (250, "بازیکن باتجربه"),
    (500, "بازیکن حرفه‌ای"),
    (1000, "استاد مافیا"),
    (2000, "افسانه مافیا"),
)

async def ensure_achievements(session: AsyncSession) -> None:
    existing = {x.key: x for x in (await session.execute(select(Achievement))).scalars().all()}
    for key, name, desc, icon, points in ACHIEVEMENTS:
        if key not in existing:
            session.add(Achievement(key=key, name_fa=name, description=desc, icon=icon, points=points))
    await session.flush()


def rank_for_score(score: int) -> str:
    rank = RANKS[0][1]
    for minimum, name in RANKS:
        if score >= minimum:
            rank = name
    return rank

async def _award(session: AsyncSession, user: User, achievement: Achievement) -> bool:
    exists = await session.scalar(select(UserAchievement.id).where(
        UserAchievement.user_id == user.id, UserAchievement.achievement_id == achievement.id
    ))
    if exists:
        return False
    session.add(UserAchievement(user_id=user.id, achievement_id=achievement.id))
    user.achievements_count += 1
    user.score += achievement.points
    return True

async def update_user_progress(session: AsyncSession, user: User) -> list[Achievement]:
    await ensure_achievements(session)
    achievements = {x.key: x for x in (await session.execute(select(Achievement))).scalars().all()}
    earned: list[Achievement] = []
    checks = {
        "first_game": user.games_played >= 1,
        "first_win": user.games_won >= 1,
        "ten_games": user.games_played >= 10,
        "ten_wins": user.games_won >= 10,
        "mafia_master": user.mafia_wins >= 10,
        "citizen_master": user.citizen_wins >= 10,
        "independent_master": user.independent_wins >= 5,
        "challenge_10": user.challenges >= 10,
        "challenge_50": user.challenges >= 50,
    }
    for key, ok in checks.items():
        if ok and await _award(session, user, achievements[key]):
            earned.append(achievements[key])
    return earned

async def record_game_result(session: AsyncSession, game_id: int, winner: str) -> dict[int, list[Achievement]]:
    result = await session.execute(select(GamePlayer, User, Role).outerjoin(Role, Role.id == GamePlayer.role_id).where(GamePlayer.game_id == game_id))
    newly_earned: dict[int, list[Achievement]] = {}
    for player, user, role in result.all():
        base = 10
        winning = (
            (winner == "mafia" and role and role.team == "mafia")
            or (winner == "citizen" and role and role.team == "citizen")
            or (winner == "independent" and role and role.team == "independent")
            or (winner == "citizen_independent" and role and role.team in {"citizen", "independent"})
        )
        user.score += base
        if winning:
            user.score += 20
        earned = await update_user_progress(session, user)
        if earned:
            newly_earned[user.id] = earned
    return newly_earned

async def leaderboard(session: AsyncSession, limit: int = 10, team: str | None = None):
    query = select(User).where(User.is_active.is_(True), User.games_played > 0)
    if team == "mafia":
        query = query.order_by(User.mafia_wins.desc(), User.score.desc(), User.games_won.desc())
    elif team == "citizen":
        query = query.order_by(User.citizen_wins.desc(), User.score.desc(), User.games_won.desc())
    else:
        query = query.order_by(User.score.desc(), User.games_won.desc(), User.games_played.desc())
    return list((await session.execute(query.limit(limit))).scalars().all())

async def user_achievements(session: AsyncSession, user_id: int):
    return list((await session.execute(select(Achievement).join(UserAchievement, UserAchievement.achievement_id == Achievement.id).where(UserAchievement.user_id == user_id).order_by(UserAchievement.earned_at.desc()))).scalars().all())


async def achievement_progress(session: AsyncSession, user: User) -> list[tuple[Achievement, bool, int, int | None]]:
    """Return every achievement with earned state and current/target progress."""
    await ensure_achievements(session)
    achievements = {a.key: a for a in (await session.execute(select(Achievement))).scalars().all()}
    earned_ids = set((await session.execute(
        select(UserAchievement.achievement_id).where(UserAchievement.user_id == user.id)
    )).scalars().all())
    progress = {
        "first_game": (user.games_played, 1),
        "first_win": (user.games_won, 1),
        "ten_games": (user.games_played, 10),
        "ten_wins": (user.games_won, 10),
        "mafia_master": (user.mafia_wins, 10),
        "citizen_master": (user.citizen_wins, 10),
        "independent_master": (user.independent_wins, 5),
        "challenge_10": (user.challenges, 10),
        "challenge_50": (user.challenges, 50),
    }
    rows = []
    for key, *_ in ACHIEVEMENTS:
        achievement = achievements[key]
        current, target = progress.get(key, (0, None))
        rows.append((achievement, achievement.id in earned_ids, min(current, target) if target else current, target))
    return rows
