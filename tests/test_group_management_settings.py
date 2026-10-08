from types import SimpleNamespace

from app.handlers.keyboards import group_birthday_menu, group_list_keyboard, group_notification_settings_menu


def _callbacks(markup):
    return [
        button.callback_data
        for row in markup.inline_keyboard
        for button in row
        if button.callback_data
    ]


def test_group_birthday_menu_has_group_defaults_and_player_birthday_entry():
    settings = SimpleNamespace(birthday_enabled=True, birthday_media_enabled=False)
    callbacks = _callbacks(group_birthday_menu(42, settings))
    assert "groupbirthday:toggle:42:birthday_enabled" in callbacks
    assert "groupmgmt:birthday_list:42" in callbacks
    assert "groupbirthday:toggle:42:birthday_media_enabled" in callbacks
    assert "groupbirthday:media:42" in callbacks
    assert "groupbirthday:message:42" in callbacks
    assert "menu:group_management" in callbacks


def test_notification_group_selector_targets_notification_purpose():
    groups = [SimpleNamespace(id=42, title="گروه تست", telegram_id=-10042)]
    callbacks = _callbacks(group_list_keyboard(groups, "notifications"))
    assert callbacks == ["groupmgmt:select:notifications:42", "menu:group_management"]


def test_group_notification_buttons_keep_selected_group():
    settings = SimpleNamespace(notification_settings='{"game_start": true}')
    callbacks = _callbacks(group_notification_settings_menu(42, settings))
    assert all(c.startswith("groupnotify:toggle:42:") for c in callbacks[:-1])
    assert callbacks[-1] == "menu:group_management"


def test_player_action_confirmation_callbacks():
    from app.handlers.keyboards import player_action_confirm_keyboard, faceoff_confirm_keyboard, replace_confirm_keyboard

    assert "gameadmin:player_target:42:slaughter:7:confirm" in _callbacks(player_action_confirm_keyboard(42, "slaughter", 7))
    assert "gameadmin:player_target:42:extra_turn:7:confirm" in _callbacks(player_action_confirm_keyboard(42, "extra_turn", 7))
    assert "gameadmin:faceoff_to:42:7:9:confirm" in _callbacks(faceoff_confirm_keyboard(42, 7, 9))
    assert "gameadmin:player_replace_to:42:7:9:confirm" in _callbacks(replace_confirm_keyboard(42, 7, 9))
