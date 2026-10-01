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
    game = Game(game_key="test", group_id=1, scenario_id=1)
    assert game.auto_play is False
    assert game.turn_color == "پیش‌فرض"
    assert game.challenge_color == "پیش‌فرض"
    assert game.reserve_enabled is True
