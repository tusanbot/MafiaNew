import asyncio
from types import SimpleNamespace

from app.handlers.keyboards import InlineKeyboardMarkup
from app.handlers.menu import _result_private_keyboard
from app.handlers.text_commands import _is_group_manager, _normalize_command_text


class _Session:
    def __init__(self, user_id: int):
        self.user = SimpleNamespace(id=user_id)

    async def scalar(self, _query):
        return self.user


class _Bot:
    async def get_chat_member(self, *_args, **_kwargs):
        raise AssertionError("host-only checks must not fall back to Telegram group-admin status")


def test_disciplinary_manager_check_accepts_only_game_host():
    game = SimpleNamespace(host_user_id=101)
    host_message = SimpleNamespace(from_user=SimpleNamespace(id=101), chat=SimpleNamespace(id=-1001))
    admin_message = SimpleNamespace(from_user=SimpleNamespace(id=202), chat=SimpleNamespace(id=-1001))

    assert asyncio.run(_is_group_manager(_Bot(), _Session(101), game, host_message, require_host=True))
    assert not asyncio.run(_is_group_manager(_Bot(), _Session(202), game, admin_message, require_host=True))


def test_warning_removal_aliases_normalize_consistently():
    assert _normalize_command_text("  تذکر   منفی  ") == "تذکر منفی"
    assert _normalize_command_text("حذف تذکر 2") == "حذف تذکر 2"


def test_private_result_keyboard_contains_all_three_tabs():
    keyboard = _result_private_keyboard(73)
    callbacks = [
        button.callback_data
        for row in keyboard.inline_keyboard
        for button in row
    ]
    assert callbacks == [
        "gameresult:view:ranking:73",
        "gameresult:view:roles:73",
        "gameresult:view:result:73",
    ]
