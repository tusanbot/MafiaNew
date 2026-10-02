from sqlalchemy import select, func
import json
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import Achievement, GameEvent, GamePlayer, Role, User, UserAchievement, UserRoleStat, Vote

ACHIEVEMENTS = (
    ("first_game", "اولین بازی", "اولین بازی کامل‌شده", "🎮", 10),
    ("first_win", "اولین برد", "اولین برد در بازی", "🏆", 20),
    ("ten_games", "بازیکن باتجربه", "تکمیل ۱۰ بازی", "⭐", 30),
    ("ten_wins", "برنده حرفه‌ای", "کسب ۱۰ برد", "🥇", 50),
    ("mafia_20", "مافیای کارکشته", "کسب ۲۰ برد با تیم مافیا", "🔴", 60),
    ("mafia_50", "مافیای افسانه‌ای", "کسب ۵۰ برد با تیم مافیا", "🔴", 120),
    ("citizen_20", "شهروند کارکشته", "کسب ۲۰ برد با تیم شهروند", "🔵", 60),
    ("citizen_50", "شهروند افسانه‌ای", "کسب ۵۰ برد با تیم شهروند", "🔵", 120),
    ("independent_3", "مستقل کارکشته", "کسب ۳ برد با تیم مستقل", "🧭", 60),
    ("independent_5", "ارتش تک نفره", "کسب ۵ برد با تیم مستقل", "⚔️", 100),
    ("challenge_100", "چالش‌گر", "ثبت ۱۰۰ چالش", "⚔️", 100),
    ("challenge_games_50", "چالش‌گر حرفه‌ای", "حضور در ۵۰ بازی دارای چالش", "🔥", 100),
    ("first_kill", "اولین شات", "ثبت اولین شات موفق", "🎯", 20),
    ("first_save", "نجات‌بخش", "ثبت اولین نجات موفق", "🩺", 20),
    ("first_investigation", "کارآگاه موفق", "اولین تحقیق موفق علیه مافیا", "🔎", 20),
    ("ten_correct_votes", "رأی‌زن دقیق", "ثبت ۱۰ رأی درست علیه مافیا", "🎯", 40),
    ("three_win_streak", "استرایکر", "کسب ۳ برد متوالی", "🎯", 30),
    ("five_win_streak", "ابر استرایکر", "کسب ۵ برد متوالی", "⚡", 60),
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
        achievement = existing.get(key)
        if achievement is None:
            session.add(Achievement(key=key, name_fa=name, description=desc, icon=icon, points=points))
        else:
            achievement.name_fa = name
            achievement.description = desc
            achievement.icon = icon
            achievement.points = points
    await session.flush()


def rank_for_score(score: int) -> str:
    rank = RANKS[0][1]
    for minimum, name in RANKS:
        if score >= minimum:
            rank = name
    return rank



def rank_progress(score: int) -> tuple[str, int | None, int]:
    """Return current rank, next threshold, and points remaining to it."""
    current = RANKS[0][1]
    next_threshold = None
    for index, (minimum, name) in enumerate(RANKS):
        if score >= minimum:
            current = name
            next_threshold = RANKS[index + 1][0] if index + 1 < len(RANKS) else None
    remaining = max(0, next_threshold - score) if next_threshold is not None else 0
    return current, next_threshold, remaining

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
        "mafia_20": user.mafia_wins >= 10,
        "citizen_20": user.citizen_wins >= 10,
        "independent_3": user.independent_wins >= 1,
        "independent_5": user.independent_wins >= 3,
        "challenge_100": user.challenges >= 10,
        "challenge_games_50": user.challenges >= 50,
        "first_kill": user.kills >= 1,
        "first_save": user.saves >= 1,
        "first_investigation": user.investigation_hits >= 1,
        "ten_correct_votes": user.correct_votes >= 10,
        "three_win_streak": user.best_win_streak >= 3,
        "five_win_streak": user.best_win_streak >= 5,
    }
    for key, ok in checks.items():
        if ok and await _award(session, user, achievements[key]):
            earned.append(achievements[key])
    return earned

def performance_score(*, kills: int, saves: int, investigation_hits: int, correct_votes: int, accepted_challenges: int, faceoff_wins: int, survived: bool) -> int:
    """Bound measurable in-game performance at 30 points per completed game."""
    return min(
        30,
        kills * 8
        + saves * 6
        + investigation_hits * 5
        + correct_votes * 2
        + accepted_challenges * 4
        + faceoff_wins * 6
        + (3 if survived else 0),
    )

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


async def record_game_result(session: AsyncSession, game_id: int, winner: str) -> dict[int, dict]:
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
        performance = performance_score(
            kills=kills[user.id],
            saves=saves[user.id],
            investigation_hits=investigation_hits[user.id],
            correct_votes=correct_votes[user.id],
            accepted_challenges=accepted_challenges[user.id],
            faceoff_wins=faceoff_wins[user.id],
            survived=player.alive,
        )
        result_score = 20 if winning else 0
        score_before = user.score
        rank_before = rank_for_score(score_before)
        score_delta = 5 + result_score + performance
        user.score += score_delta
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
        newly_earned[user.id] = {"achievements": earned, "score_delta": score_delta, "score_before": score_before, "score_after": user.score, "rank_before": rank_before, "rank_after": rank_for_score(user.score), "stats": {"kills": kills[user.id], "saves": saves[user.id], "investigations": investigations[user.id], "investigation_hits": investigation_hits[user.id], "correct_votes": correct_votes[user.id], "accepted_challenges": accepted_challenges[user.id], "faceoffs": faceoff_counts[user.id], "faceoff_wins": faceoff_wins[user.id], "survived": bool(player.alive), "performance": performance, "won": bool(winning)}}
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
    challenge_games = int(await session.scalar(
        select(func.count(func.distinct(GameEvent.game_id))).where(
            GameEvent.event_type == "challenge_request",
            GameEvent.actor_user_id == user.id,
        )
    ) or 0)
    progress = {
        "first_game": (user.games_played, 1),
        "first_win": (user.games_won, 1),
        "ten_games": (user.games_played, 10),
        "ten_wins": (user.games_won, 10),
        "mafia_20": (user.mafia_wins, 20),
        "mafia_50": (user.mafia_wins, 50),
        "citizen_20": (user.citizen_wins, 20),
        "citizen_50": (user.citizen_wins, 50),
        "independent_3": (user.independent_wins, 3),
        "independent_5": (user.independent_wins, 5),
        "challenge_100": (user.challenges, 100),
        "challenge_games_50": (challenge_games, 50),
        "first_kill": (user.kills, 1),
        "first_save": (user.saves, 1),
        "first_investigation": (user.investigation_hits, 1),
        "ten_correct_votes": (user.correct_votes, 10),
        "three_win_streak": (user.best_win_streak, 3),
        "five_win_streak": (user.best_win_streak, 5),
    }
    rows = []
    for key, *_ in ACHIEVEMENTS:
        achievement = achievements[key]
        current, target = progress.get(key, (0, None))
        rows.append((achievement, achievement.id in earned_ids, min(current, target) if target else current, target))
    return rows
