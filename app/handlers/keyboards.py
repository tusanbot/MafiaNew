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


def player_target_keyboard(prefix: str, game_key: str, players) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for player, user, *rest in players:
        builder.row(InlineKeyboardButton(
            text=f"{player.seat}. {user.display_name or user.first_name}",
            callback_data=f"{prefix}:{game_key}:{user.id}",
        ))
    return builder.as_markup()

def night_action_keyboard(game_key: str, action_type: str, players) -> InlineKeyboardMarkup:
    return player_target_keyboard(f"night:{action_type}", game_key, players)

def vote_keyboard(game_key: str, players) -> InlineKeyboardMarkup:
    return player_target_keyboard("vote", game_key, players)

def day_keyboard(game_key: str, players=None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if players:
        builder.row(InlineKeyboardButton(text="چالش یک بازیکن", callback_data=f"day:challenge:{game_key}"))
    builder.row(InlineKeyboardButton(text="شروع رأی‌گیری", callback_data=f"day:vote:{game_key}"))
    return builder.as_markup()

def continue_night_keyboard(game_key: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="ارسال اقدامات شب", callback_data=f"night:resolve:{game_key}"))
    return builder.as_markup()


def challenge_keyboard(game_key: str, players) -> InlineKeyboardMarkup:
    return player_target_keyboard("challenge", game_key, players)

def challenge_response_keyboard(game_key: str, event_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="پذیرش چالش", callback_data=f"challenge:accept:{game_key}:{event_id}"),
        InlineKeyboardButton(text="رد چالش", callback_data=f"challenge:reject:{game_key}:{event_id}"),
    )
    return builder.as_markup()


def day_turn_keyboard(game_key: str, is_current_speaker: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="درخواست چالش", callback_data=f"turn:request_challenge:{game_key}"))
    if is_current_speaker:
        builder.row(InlineKeyboardButton(text="نکست ترن", callback_data=f"turn:next:{game_key}"))
    return builder.as_markup()


def challenge_requests_keyboard(game_key: str, requests) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for event, data in requests:
        builder.row(InlineKeyboardButton(
            text=f"چالش {data.get('requester_name', 'بازیکن')}",
            callback_data=f"challenge:grant:{game_key}:{event.id}",
        ))
    return builder.as_markup()


def challenge_placement_keyboard(game_key: str, event_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="قبل از صحبت", callback_data=f"challenge:place:{game_key}:{event_id}:before"),
        InlineKeyboardButton(text="بعد از صحبت", callback_data=f"challenge:place:{game_key}:{event_id}:after"),
    )
    return builder.as_markup()
