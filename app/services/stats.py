from sqlalchemy import select, func
import json
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import Achievement, GameEvent, GamePlayer, Role, User, UserAchievement, UserRoleStat, Vote

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
    ("first_kill", "اولین شکار", "ثبت اولین کشت موفق", "🗡", 20),
    ("first_save", "نجات‌بخش", "ثبت اولین نجات موفق", "🩺", 20),
    ("first_investigation", "کارآگاه موفق", "اولین تحقیق موفق علیه مافیا", "🔎", 20),
    ("ten_correct_votes", "رأی‌زن دقیق", "ثبت ۱۰ رأی درست علیه مافیا", "🎯", 40),
    ("three_win_streak", "فرم برد", "کسب ۳ برد متوالی", "🔥", 30),
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
        "first_kill": user.kills >= 1,
        "first_save": user.saves >= 1,
        "first_investigation": user.investigation_hits >= 1,
        "ten_correct_votes": user.correct_votes >= 10,
        "three_win_streak": user.best_win_streak >= 3,
    }
    for key, ok in checks.items():
        if ok and await _award(session, user, achievements[key]):
            earned.append(achievements[key])
    return earned

async def _collect_game_stats(session: AsyncSession, game_id: int):
    events = list((await session.execute(
        select(GameEvent).where(GameEvent.game_id == game_id).order_by(GameEvent.id)
    )).scalars().all())
    actions, resolved, faceoffs, challenges = [], [], [], []
    for event in events:
        try:
            data = json.loads(event.payload or "{}")
        except Exception:
            data = {}
        if event.event_type == "night_action":
            actions.append((event, data))
        elif event.event_type == "night_resolved":
            resolved.append(data)
        elif "faceoff" in event.event_type.lower() or "face_off" in event.event_type.lower():
            faceoffs.append((event, data))
        elif event.event_type == "challenge_request":
            challenges.append(data)
    votes = list((await session.execute(select(Vote).where(Vote.game_id == game_id))).scalars().all())
    return actions, resolved, votes, faceoffs, challenges


async def record_game_result(session: AsyncSession, game_id: int, winner: str) -> dict[int, list[Achievement]]:
    result = await session.execute(select(GamePlayer, User, Role).outerjoin(Role, Role.id == GamePlayer.role_id).where(GamePlayer.game_id == game_id))
    rows = result.all()
    actions, resolved, votes, faceoffs, challenges = await _collect_game_stats(session, game_id)
    by_user = {user.id: (player, user, role) for player, user, role in rows}
    kills = {uid: 0 for uid in by_user}; saves = {uid: 0 for uid in by_user}
    investigations = {uid: 0 for uid in by_user}; investigation_hits = {uid: 0 for uid in by_user}
    correct_votes = {uid: 0 for uid in by_user}; accepted_challenges = {uid: 0 for uid in by_user}
    faceoff_counts = {uid: 0 for uid in by_user}; faceoff_wins = {uid: 0 for uid in by_user}
    killed_ids = {int(d["killed_user_id"]) for d in resolved if d.get("killed_user_id")}
    saved_rounds = {int(d.get("round_no", 0)) for d in resolved if d.get("saved")}
    for event, data in actions:
        actor = event.actor_user_id
        if actor not in by_user:
            continue
        if data.get("action_type") == "mafia_kill" and int(data.get("target_user_id", 0)) in killed_ids:
            kills[actor] += 1
        elif data.get("action_type") == "doctor_save" and int(data.get("round_no", 0)) in saved_rounds:
            saves[actor] += 1
        elif data.get("action_type") == "detective_check":
            investigations[actor] += 1
            target = by_user.get(int(data.get("target_user_id", 0)))
            if target and target[2] and target[2].team == "mafia":
                investigation_hits[actor] += 1
    for vote in votes:
        voter, target = by_user.get(vote.voter_user_id), by_user.get(vote.target_user_id)
        if voter and target and voter[2] and target[2] and voter[2].team != "mafia" and target[2].team == "mafia":
            correct_votes[vote.voter_user_id] += 1
    for data in challenges:
        if data.get("status") == "accepted":
            uid = int(data.get("requester_id", 0))
            if uid in accepted_challenges:
                accepted_challenges[uid] += 1
    for event, data in faceoffs:
        uid = event.actor_user_id
        if uid in faceoff_counts:
            faceoff_counts[uid] += 1
        if data.get("winner_user_id") is not None and uid == int(data["winner_user_id"]):
            faceoff_wins[uid] += 1
    newly_earned = {}
    for player, user, role in rows:
        winning = ((winner == "mafia" and role and role.team == "mafia") or
                   (winner == "citizen" and role and role.team == "citizen") or
                   (winner == "independent" and role and role.team == "independent") or
                   (winner == "citizen_independent" and role and role.team in {"citizen", "independent"}))
        # Performance score: participation + result + measurable actions.
        # A per-game cap prevents one unusually active game from dominating the leaderboard.
        performance_score = min(
            30,
            kills[user.id] * 8
            + saves[user.id] * 6
            + investigation_hits[user.id] * 5
            + correct_votes[user.id] * 2
            + accepted_challenges[user.id] * 4
            + faceoff_wins[user.id] * 6
            + (3 if player.alive else 0)
        )
        result_score = 20 if winning else 0
        user.score += 5 + result_score + performance_score
        user.win_streak = user.win_streak + 1 if winning else 0
        user.best_win_streak = max(user.best_win_streak, user.win_streak)
        user.kills += kills[user.id]; user.saves += saves[user.id]
        user.investigations += investigations[user.id]; user.investigation_hits += investigation_hits[user.id]
        user.correct_votes += correct_votes[user.id]; user.challenges_accepted += accepted_challenges[user.id]
        user.faceoffs += faceoff_counts[user.id]; user.faceoff_wins += faceoff_wins[user.id]
        if player.exit_type == "kick": user.kicks += 1
        if player.alive: user.games_survived += 1
        if role:
            role_stat = await session.scalar(select(UserRoleStat).where(UserRoleStat.user_id == user.id, UserRoleStat.role_id == role.id))
            if not role_stat:
                role_stat = UserRoleStat(user_id=user.id, role_id=role.id); session.add(role_stat); await session.flush()
            role_stat.games += 1; role_stat.wins += int(winning)
            role_stat.kills += kills[user.id]; role_stat.saves += saves[user.id]
            role_stat.investigations += investigations[user.id]; role_stat.investigation_hits += investigation_hits[user.id]
        earned = await update_user_progress(session, user)
        if earned: newly_earned[user.id] = earned
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
        "first_kill": (user.kills, 1),
        "first_save": (user.saves, 1),
        "first_investigation": (user.investigation_hits, 1),
        "ten_correct_votes": (user.correct_votes, 10),
        "three_win_streak": (user.best_win_streak, 3),
    }
    rows = []
    for key, *_ in ACHIEVEMENTS:
        achievement = achievements[key]
        current, target = progress.get(key, (0, None))
        rows.append((achievement, achievement.id in earned_ids, min(current, target) if target else current, target))
    return rows
