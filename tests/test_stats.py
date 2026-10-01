from app.services.stats import rank_for_score, rank_progress, performance_score, ACHIEVEMENTS


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
    from app.db.models import User, UserRoleStat, Scenario, ScenarioRole
    user_columns = {column.key for column in inspect(User).columns}
    assert {
        "kills", "saves", "investigations", "investigation_hits",
        "correct_votes", "challenges_accepted", "faceoffs", "faceoff_wins",
        "kicks", "games_survived", "win_streak", "best_win_streak",
    } <= user_columns
    role_columns = {column.key for column in inspect(UserRoleStat).columns}
    scenario_columns = {column.key for column in inspect(Scenario).columns}
    assert {"games", "wins", "kills", "saves", "investigations", "investigation_hits"} <= role_columns
    assert {"description", "challenge_mode", "challenge_limit"} <= scenario_columns
    scenario_role_columns = {column.key for column in inspect(ScenarioRole).columns}
    assert {"scenario_id", "role_id", "count", "position"} <= scenario_role_columns


def test_rank_progress():
    assert rank_progress(0) == ("تازه‌وارد", 100, 100)
    assert rank_progress(100) == ("بازیکن", 250, 150)
    assert rank_progress(250) == ("بازیکن باتجربه", 500, 250)
    assert rank_progress(500) == ("بازیکن حرفه‌ای", 1000, 500)
    assert rank_progress(2500) == ("افسانه مافیا", None, 0)


def test_performance_score_is_weighted_and_capped():
    assert performance_score(
        kills=1, saves=1, investigation_hits=1,
        correct_votes=2, accepted_challenges=1,
        faceoff_wins=1, survived=True,
    ) == 30
    assert performance_score(
        kills=0, saves=0, investigation_hits=0,
        correct_votes=0, accepted_challenges=0,
        faceoff_wins=0, survived=True,
    ) == 3


def test_requested_achievement_targets():
    rows = {row[0]: row for row in ACHIEVEMENTS}
    assert rows["three_win_streak"][1] == "استرایکر"
    assert rows["five_win_streak"][1] == "ابر استرایکر"
    assert rows["independent_master"][2] == "کسب ۱ برد با تیم مستقل"
    assert rows["army_one"][2] == "کسب ۳ برد با تیم مستقل"
