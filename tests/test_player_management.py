from types import SimpleNamespace

from app.handlers.keyboards import (
    player_faceoff_destination_keyboard,
    player_management_menu,
    player_replace_destination_keyboard,
    player_target_management_keyboard,
)
from app.services.player_management import (
    apply_kick,
    grant_extra_turn,
    parse_turn_payload,
    remove_player,
    restore_removed_player,
    silence_target_round,
    swap_roles_for_faceoff,
)


def _callbacks(markup):
    return [
        button.callback_data
        for row in markup.inline_keyboard
        for button in row
        if button.callback_data
    ]


def _player(user_id=10, seat=1, role_id=100, alive=True, exit_type=None):
    return SimpleNamespace(
        user_id=user_id,
        seat=seat,
        role_id=role_id,
        alive=alive,
        exit_type=exit_type,
        silence_until_round=None,
        extra_turn_round=None,
        is_reserved=False,
        is_substitute=False,
    )


def _user(score=10, kicks=0):
    return SimpleNamespace(score=score, kicks=kicks)


def test_remove_player_is_restorable_as_death():
    player = _player()
    remove_player(player, "death")
    assert (player.alive, player.exit_type) == (False, "death")
    assert restore_removed_player(player) is True
    assert (player.alive, player.exit_type) == (True, None)


def test_slaughter_and_kick_are_not_restorable():
    player = _player()
    remove_player(player, "slaughter")
    assert restore_removed_player(player) is False
    assert (player.alive, player.exit_type) == (False, "slaughter")

    player = _player()
    apply_kick(player, _user(score=7, kicks=2))
    assert restore_removed_player(player) is False
    assert (player.alive, player.exit_type) == (False, "kick")


def test_kick_updates_penalty_and_counter():
    player = _player()
    user = _user(score=7, kicks=2)
    apply_kick(player, user)
    assert user.kicks == 3
    assert user.score == 6


def test_faceoff_swaps_roles_and_removes_source():
    source = _player(user_id=10, role_id=100)
    destination = _player(user_id=20, role_id=200)
    swap_roles_for_faceoff(source, destination)
    assert source.role_id == 200
    assert destination.role_id == 100
    assert (source.alive, source.exit_type) == (False, "faceoff")
    assert destination.alive is True


def test_silence_skips_current_round_when_turn_already_passed():
    player = _player(user_id=20)
    round_no = silence_target_round(
        player, 3, "day", {"queue": [10, 20, 30], "index": 1}
    )
    assert round_no == 4
    assert player.silence_until_round == 4


def test_silence_applies_current_round_when_turn_is_not_passed():
    player = _player(user_id=30)
    round_no = silence_target_round(
        player, 3, "day", {"queue": [10, 20, 30], "index": 1}
    )
    assert round_no == 3
    assert player.silence_until_round == 3


def test_silence_at_night_targets_next_round():
    player = _player(user_id=20)
    assert silence_target_round(player, 3, "night") == 4
    assert player.silence_until_round == 4


def test_extra_turn_is_bound_to_current_round():
    player = _player()
    grant_extra_turn(player, 5)
    assert player.extra_turn_round == 5


def test_invalid_turn_payload_is_safe():
    assert parse_turn_payload("{not-json") == {}
    assert parse_turn_payload("[]") == {}


def test_player_management_back_buttons_return_to_players_menu():
    assert "gameadmin:active:42" in _callbacks(player_management_menu(42))
    assert "gameadmin:players:42" in _callbacks(
        player_target_management_keyboard(42, "remove", [])
    )
    assert "gameadmin:players:42" in _callbacks(
        player_faceoff_destination_keyboard(42, 10, [])
    )
    assert "gameadmin:players:42" in _callbacks(
        player_replace_destination_keyboard(42, 10, [])
    )


def test_faceoff_and_replace_callback_shapes():
    class P:
        seat = 2
        is_reserved = False
        alive = True

    class U:
        id = 20
        display_name = "بازیکن"

    faceoff = _callbacks(player_faceoff_destination_keyboard(42, 10, [(P(), U())]))
    replace = _callbacks(player_replace_destination_keyboard(42, 10, [(P(), U())]))
    assert "gameadmin:faceoff_to:42:10:20" in faceoff
    assert "gameadmin:player_replace_to:42:10:20" in replace
