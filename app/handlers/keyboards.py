from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def main_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="پروفایل", callback_data="menu:profile"),
        InlineKeyboardButton(text="ساخت بازی", callback_data="game:create"),
    )
    builder.row(
        InlineKeyboardButton(text="سناریوها", callback_data="menu:scenarios"),
        InlineKeyboardButton(text="راهنما", callback_data="menu:help"),
    )
    return builder.as_markup()


def lobby_keyboard(game_key: str, can_start: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="پیوستن", callback_data=f"game:join:{game_key}"),
        InlineKeyboardButton(text="ترک بازی", callback_data=f"game:leave:{game_key}"),
    )
    if can_start:
        builder.row(InlineKeyboardButton(text="شروع بازی", callback_data=f"game:start:{game_key}"))
    return builder.as_markup()


def scenario_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="کلاسیک", callback_data="scenario:classic"))
    return builder.as_markup()
