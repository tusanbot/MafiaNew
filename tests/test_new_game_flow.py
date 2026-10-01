from app.db.models import Game
from app.handlers.keyboards import (
    host_select_keyboard,
    new_game_color_keyboard,
    new_game_extras_keyboard,
    new_game_menu,
    new_game_settings_keyboard,
    scenario_select_keyboard,
)


def _callbacks(markup):
    return [
        button.callback_data
        for row in markup.inline_keyboard
        for button in row
        if button.callback_data
    ]


def test_new_game_menu_has_complete_flow() -> None:
    callbacks = _callbacks(new_game_menu(42))
    assert callbacks == [
        "newgame:scenario:42",
        "newgame:host:42",
        "newgame:settings:42",
        "newgame:extras:42",
        "newgame:create:42",
        "groupstart:root:42",
    ]


def test_new_game_submenus_return_to_draft_menu() -> None:
    assert "newgame:menu:42" in _callbacks(scenario_select_keyboard(42, []))
    assert "newgame:menu:42" in _callbacks(host_select_keyboard(42, []))
    assert "newgame:menu:42" in _callbacks(new_game_settings_keyboard(42))


def test_new_game_extra_colors_have_selection_callbacks() -> None:
    callbacks = _callbacks(new_game_extras_keyboard(42, True, "قرمز", "آبی"))
    assert "newgame:turn_color:42" in callbacks
    assert "newgame:challenge_color:42" in callbacks

    turn_callbacks = _callbacks(new_game_color_keyboard(42, "turn", "قرمز"))
    challenge_callbacks = _callbacks(new_game_color_keyboard(42, "challenge", "آبی"))
    assert "newgame:set_turn_color:42:قرمز" in turn_callbacks
    assert "newgame:set_challenge_color:42:آبی" in challenge_callbacks


def test_game_settings_schema_defaults_are_present() -> None:
    game = Game(game_key="test", group_id=1, scenario_id=1)
    assert game.auto_play is False
    assert game.turn_color == "پیش‌فرض"
    assert game.challenge_color == "پیش‌فرض"
    assert game.reserve_enabled is True
