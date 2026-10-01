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


def test_scenario_callback_shape_matches_handler() -> None:
    group_id, scenario_id = 123, 7
    callback_data = f"newgame:setscenario:{group_id}:{scenario_id}"
    parts = callback_data.split(":")
    assert len(parts) == 4
    assert parts[0:2] == ["newgame", "setscenario"]
    assert int(parts[2]) == group_id
    assert int(parts[3]) == scenario_id

def test_host_callback_shape_matches_handler() -> None:
    group_id, host_id = 123, 456789
    callback_data = f"newgame:sethost:{group_id}:{host_id}"
    parts = callback_data.split(":")
    assert len(parts) == 4
    assert parts[0:2] == ["newgame", "sethost"]
    assert int(parts[2]) == group_id
    assert int(parts[3]) == host_id

def test_host_callback_shape_matches_handler() -> None:
    group_id, host_id = 123, 456789
    callback_data = f"newgame:sethost:{group_id}:{host_id}"
    parts = callback_data.split(":")
    assert len(parts) == 4
    assert parts[0:2] == ["newgame", "sethost"]
    assert int(parts[2]) == group_id
    assert int(parts[3]) == host_id


def test_new_game_color_callbacks_have_four_parts() -> None:
    turn = "newgame:set_turn_color:123:قرمز".split(":")
    challenge = "newgame:set_challenge_color:123:آبی".split(":")
    assert len(turn) == 4
    assert turn[:2] == ["newgame", "set_turn_color"]
    assert int(turn[2]) == 123
    assert turn[3] == "قرمز"
    assert len(challenge) == 4
    assert challenge[:2] == ["newgame", "set_challenge_color"]
    assert int(challenge[2]) == 123
    assert challenge[3] == "آبی"


def test_night_callbacks_match_keyboard_shapes() -> None:
    resolve = "night:resolve:abc123".split(":")
    action = "night:mafia_kill:abc123:456".split(":")
    assert len(resolve) == 3
    assert resolve[0:2] == ["night", "resolve"]
    assert resolve[2] == "abc123"
    assert len(action) == 4
    assert action[0] == "night"
    assert action[1] == "mafia_kill"
    assert action[2] == "abc123"
    assert int(action[3]) == 456
