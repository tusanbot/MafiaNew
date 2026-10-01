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


def test_game_management_columns_exist() -> None:
    game_columns = {column.key for column in inspect(Game).columns}
    assert {
        "challenge_enabled",
        "challenge_mode",
        "next_host_enabled",
        "next_player_enabled",
        "next_auto_enabled",
        "auto_silence_warnings",
        "auto_kick_warnings",
        "turn_color_enabled",
        "emoji_settings",
        "challenge_limit",
    } <= game_columns


def test_player_lifecycle_columns_exist() -> None:
    from app.db.models import GamePlayer, User
    assert {
        "exit_type",
        "warning_count",
        "silence_until_round",
        "extra_turn_round",
    } <= {column.key for column in inspect(GamePlayer).columns}
    assert "score" in {column.key for column in inspect(User).columns}
