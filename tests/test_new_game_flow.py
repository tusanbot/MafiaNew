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


def test_admin_panel_keyboard_has_core_sections() -> None:
    from app.handlers.keyboards import admin_panel_menu
    callbacks = _callbacks(admin_panel_menu())
    assert callbacks == [
        "admin:dashboard",
        "admin:groups",
        "admin:scenarios",
        "admin:games",
        "admin:settings",
        "menu:root",
    ]


def test_main_menu_can_expose_admin_panel() -> None:
    from app.handlers.keyboards import main_menu
    callbacks = _callbacks(main_menu(show_admin=True))
    assert "menu:admin" in callbacks


def test_gameplay_timing_defaults_are_persisted_on_models() -> None:
    from app.db.models import Game, Scenario

    game_defaults = {c.key: c.default.arg for c in Game.__table__.columns
                     if c.key in {"turn_seconds", "challenge_seconds", "extra_challenge_seconds"}}
    scenario_defaults = {c.key: c.default.arg for c in Scenario.__table__.columns
                         if c.key in {"turn_seconds", "challenge_seconds", "extra_challenge_seconds"}}
    assert game_defaults == {"turn_seconds": 120, "challenge_seconds": 60, "extra_challenge_seconds": 60}
    assert scenario_defaults == {"turn_seconds": 120, "challenge_seconds": 60, "extra_challenge_seconds": 60}


def test_leader_callback_shapes() -> None:
    assert "leader:auto:abc123".split(":") == ["leader", "auto", "abc123"]
    parts = "leader:select:abc123:456".split(":")
    assert parts[:3] == ["leader", "select", "abc123"]
    assert int(parts[3]) == 456


def test_lobby_text_is_forced_rtl() -> None:
    text = "\u200fبازیکنان اصلی : 4/10"
    assert text.startswith("\u200f")


def test_round_controls_use_automatic_leader_and_finish_button() -> None:
    from app.handlers.keyboards import day_keyboard, leader_settings_keyboard

    class GameStub:
        challenge_enabled = True
        next_host_enabled = True
        next_player_enabled = True
        next_auto_enabled = False

    leader_markup = leader_settings_keyboard("abc", GameStub())
    callbacks = [button.callback_data for row in leader_markup.inline_keyboard for button in row]
    assert "leader:menu:abc" in callbacks

    day_markup = day_keyboard("abc")
    day_callbacks = [button.callback_data for row in day_markup.inline_keyboard for button in row]
    assert "day:finish:abc" in day_callbacks


def test_turn_keyboard_contains_challenge_and_next_buttons() -> None:
    from app.handlers.keyboards import day_turn_keyboard
    callbacks = _callbacks(day_turn_keyboard("abc", True, True, True, "پیش‌فرض", "پیش‌فرض", True, True))
    assert "turn:request_challenge:abc" in callbacks
    assert "turn:next:abc" in callbacks


def test_challenge_requests_are_rendered_on_turn_keyboard() -> None:
    from app.handlers.keyboards import day_turn_keyboard
    class Event:
        id = 17
    markup = day_turn_keyboard("abc", True, True, True, "پیش‌فرض", "پیش‌فرض", True, True, [(Event(), {"requester_name": "رضا"})])
    callbacks = _callbacks(markup)
    assert "challenge:grant:abc:17" in callbacks


def test_night_control_keyboard_has_locks_and_start_day() -> None:
    from app.handlers.keyboards import continue_night_keyboard
    callbacks = _callbacks(continue_night_keyboard("abc", True, False))
    assert "night:resolve:abc" in callbacks
    assert "night:lock:abc:night_lock" in callbacks
    assert "night:lock:abc:chat_lock" in callbacks
    assert "night:start_day:abc" in callbacks
