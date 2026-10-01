from sqlalchemy import inspect

from app.db.models import Game


def test_game_model_matches_game_settings_schema() -> None:
    columns = {column.key for column in inspect(Game).columns}
    assert {
        "auto_play",
        "turn_color",
        "challenge_color",
        "reserve_enabled",
    } <= columns


def test_game_settings_have_expected_defaults() -> None:
    defaults = {
        column.key: column.default.arg
        for column in Game.__table__.columns
        if column.key in {"auto_play", "turn_color", "challenge_color", "reserve_enabled"}
    }
    assert defaults == {
        "auto_play": False,
        "turn_color": "پیش‌فرض",
        "challenge_color": "پیش‌فرض",
        "reserve_enabled": True,
    }
