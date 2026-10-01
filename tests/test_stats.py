from app.services.stats import rank_for_score, ACHIEVEMENTS


def test_rank_progression():
    assert rank_for_score(0) == "تازه‌وارد"
    assert rank_for_score(100) == "بازیکن"
    assert rank_for_score(250) == "بازیکن باتجربه"
    assert rank_for_score(500) == "بازیکن حرفه‌ای"
    assert rank_for_score(1000) == "استاد مافیا"
    assert rank_for_score(2000) == "افسانه مافیا"


def test_achievement_keys_are_unique():
    keys = [row[0] for row in ACHIEVEMENTS]
    assert len(keys) == len(set(keys))


def test_detailed_user_stats_columns_exist():
    from sqlalchemy import inspect
    from app.db.models import User, UserRoleStat
    user_columns = {column.key for column in inspect(User).columns}
    assert {
        "kills", "saves", "investigations", "investigation_hits",
        "correct_votes", "challenges_accepted", "faceoffs", "faceoff_wins",
        "kicks", "games_survived", "win_streak", "best_win_streak",
    } <= user_columns
    role_columns = {column.key for column in inspect(UserRoleStat).columns}
    assert {"games", "wins", "kills", "saves", "investigations", "investigation_hits"} <= role_columns
