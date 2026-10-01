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
