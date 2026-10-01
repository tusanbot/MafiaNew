from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def _back(builder: InlineKeyboardBuilder, callback_data: str = "menu:root") -> None:
    builder.row(InlineKeyboardButton(text="بازگشت", callback_data=callback_data))


def main_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="مدیریت گروه", callback_data="menu:group_management"))
    builder.row(
        InlineKeyboardButton(text="سناریوها", callback_data="menu:scenarios"),
        InlineKeyboardButton(text="تنظیمات ربات", callback_data="menu:bot_settings"),
    )
    builder.row(
        InlineKeyboardButton(text="پروفایل", callback_data="menu:profile"),
        InlineKeyboardButton(text="رتبه بندی", callback_data="menu:ranking"),
    )
    _back(builder, "menu:root")
    return builder.as_markup()


def group_management_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="مدیریت بازی", callback_data="groupmgmt:games"))
    builder.row(InlineKeyboardButton(text="قفل گروه", callback_data="groupmgmt:locks"))
    _back(builder)
    return builder.as_markup()


def group_list_keyboard(groups, purpose: str = "games") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for group in groups:
        title = group.title or f"گروه {group.telegram_id}"
        builder.row(InlineKeyboardButton(text=title[:64], callback_data=f"groupmgmt:select:{purpose}:{group.id}"))
    _back(builder, "menu:group_management")
    return builder.as_markup()


def group_game_menu(group_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="مدیریت بازی فعال", callback_data=f"groupgame:active:{group_id}"))
    builder.row(InlineKeyboardButton(text="تاریخچه بازی ها", callback_data=f"groupgame:history:{group_id}"))
    _back(builder, "groupmgmt:games")
    return builder.as_markup()


def group_lock_keyboard(group_id: int, settings) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=f"قفل چت: {'فعال' if settings.chat_lock else 'غیرفعال'}",
            callback_data=f"grouplock:toggle:{group_id}:chat_lock",
        )
    )
    builder.row(
        InlineKeyboardButton(
            text=f"قفل شب: {'فعال' if settings.night_lock else 'غیرفعال'}",
            callback_data=f"grouplock:toggle:{group_id}:night_lock",
        )
    )
    builder.row(
        InlineKeyboardButton(
            text=f"قفل نوبت: {'فعال' if settings.turn_lock else 'غیرفعال'}",
            callback_data=f"grouplock:toggle:{group_id}:turn_lock",
        )
    )
    _back(builder, "menu:group_management")
    return builder.as_markup()


def active_game_menu(group_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="اطلاعات بازی", callback_data=f"gameadmin:info:{group_id}"))
    builder.row(InlineKeyboardButton(text="مدیریت بازیکنان", callback_data=f"gameadmin:players:{group_id}"))
    builder.row(InlineKeyboardButton(text="امکانات بازی", callback_data=f"gameadmin:features:{group_id}"))
    builder.row(InlineKeyboardButton(text="امکانات اضافی", callback_data=f"gameadmin:extras:{group_id}"))
    _back(builder, f"groupmgmt:select:{group_id}")
    return builder.as_markup()


def player_management_menu(group_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for key, label in (
        ("remove", "حذف بازیکن"),
        ("replace", "جایگزین بازیکن"),
        ("silence", "سکوت"),
        ("extra_turn", "ترن اضافه"),
        ("kick", "کیک"),
        ("birthday", "تولد بازیکن"),
        ("faceoff", "فیس آف"),
        ("warning", "تذکر"),
    ):
        builder.row(InlineKeyboardButton(text=label, callback_data=f"gameadmin:player_action:{group_id}:{key}"))
    _back(builder, f"gameadmin:active:{group_id}")
    return builder.as_markup()


def game_features_menu(group_id: int, challenge_mode: str = "در حال دریافت", next_status: str = "در حال دریافت") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=f"وضعیت چالش: {challenge_mode}", callback_data=f"gameadmin:feature:{group_id}:challenge"))
    builder.row(InlineKeyboardButton(text=f"وضعیت نکست: {next_status}", callback_data=f"gameadmin:feature:{group_id}:next"))
    builder.row(InlineKeyboardButton(text="اتمام بازی", callback_data=f"gameadmin:feature:{group_id}:finish"))
    builder.row(InlineKeyboardButton(text="لغو بازی", callback_data=f"gameadmin:feature:{group_id}:cancel"))
    builder.row(InlineKeyboardButton(text="تغییر سناریو", callback_data=f"gameadmin:feature:{group_id}:scenario"))
    builder.row(InlineKeyboardButton(text="تغییر گرداننده", callback_data=f"gameadmin:feature:{group_id}:host"))
    builder.row(InlineKeyboardButton(text="امکانات ویژه", callback_data=f"gameadmin:feature:{group_id}:special"))
    _back(builder, f"gameadmin:active:{group_id}")
    return builder.as_markup()


def game_extras_menu(group_id: int, auto_play: bool = False, turn_color: str = "پیش‌فرض", challenge_color: str = "پیش‌فرض") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text=f"بازی خودکار: {'فعال' if auto_play else 'غیرفعال'}",
        callback_data=f"gameadmin:extra:{group_id}:auto_play",
    ))
    builder.row(InlineKeyboardButton(text=f"رنگ نوبت: {turn_color}", callback_data=f"gameadmin:extra:{group_id}:turn_color"))
    builder.row(InlineKeyboardButton(text=f"رنگ چالش: {challenge_color}", callback_data=f"gameadmin:extra:{group_id}:challenge_color"))
    builder.row(InlineKeyboardButton(text="سایر امکانات", callback_data=f"gameadmin:extra:{group_id}:other"))
    _back(builder, f"gameadmin:active:{group_id}")
    return builder.as_markup()


def bot_settings_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="تنظیمات عمومی", callback_data="botsettings:general"))
    builder.row(InlineKeyboardButton(text="تنظیمات اعلان ها", callback_data="botsettings:notifications"))
    builder.row(InlineKeyboardButton(text="بازگشت", callback_data="menu:root"))
    return builder.as_markup()


def ranking_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="بازیکنان برتر", callback_data="ranking:players"))
    builder.row(InlineKeyboardButton(text="برترین مافیا", callback_data="ranking:mafia"))
    builder.row(InlineKeyboardButton(text="برترین شهروند", callback_data="ranking:citizen"))
    _back(builder)
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
    _back(builder)
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

def group_start_menu(group_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="بازی جدید", callback_data=f"groupstart:new:{group_id}"))
    builder.row(InlineKeyboardButton(text="تاریخچه بازی ها", callback_data=f"groupstart:history:{group_id}"))
    builder.row(InlineKeyboardButton(text="راهنما", callback_data=f"groupstart:help:{group_id}"))
    builder.row(InlineKeyboardButton(text="بستن", callback_data=f"groupstart:close:{group_id}"))
    return builder.as_markup()


def registration_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    # The callback message itself is the authoritative Telegram chat.
    # Never embed groups.id or any other internal identifier in this callback.
    builder.row(InlineKeyboardButton(text="ثبت گروه در ربات", callback_data="groupreg:register"))
    return builder.as_markup()


def new_game_menu(group_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="انتخاب سناریو", callback_data=f"newgame:scenario:{group_id}"))
    builder.row(InlineKeyboardButton(text="انتخاب گرداننده", callback_data=f"newgame:host:{group_id}"))
    builder.row(InlineKeyboardButton(text="تنظیمات بازی", callback_data=f"newgame:settings:{group_id}"))
    builder.row(InlineKeyboardButton(text="امکانات اضافه", callback_data=f"newgame:extras:{group_id}"))
    builder.row(InlineKeyboardButton(text="ایجاد بازی", callback_data=f"newgame:create:{group_id}"))
    builder.row(InlineKeyboardButton(text="بازگشت", callback_data=f"groupstart:root:{group_id}"))
    return builder.as_markup()


def scenario_select_keyboard(group_id: int, scenarios) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for scenario in scenarios:
        builder.row(InlineKeyboardButton(text=scenario.name_fa, callback_data=f"newgame:setscenario:{group_id}:{scenario.id}"))
    builder.row(InlineKeyboardButton(text="بازگشت", callback_data=f"newgame:menu:{group_id}"))
    return builder.as_markup()


def host_select_keyboard(group_id: int, admins) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for member in admins:
        user = member.user
        name = user.full_name or user.username or str(user.id)
        builder.row(InlineKeyboardButton(text=name[:60], callback_data=f"newgame:sethost:{group_id}:{user.id}"))
    builder.row(InlineKeyboardButton(text="بازگشت", callback_data=f"newgame:menu:{group_id}"))
    return builder.as_markup()


def new_game_settings_keyboard(group_id: int, reserve_enabled: bool = True) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=f"رزرو: {'فعال' if reserve_enabled else 'غیرفعال'}",
            callback_data=f"newgame:toggle_reserve:{group_id}",
        )
    )
    builder.row(InlineKeyboardButton(text="بازگشت", callback_data=f"newgame:menu:{group_id}"))
    return builder.as_markup()


def new_game_color_keyboard(group_id: int, kind: str, current: str = "پیش‌فرض") -> InlineKeyboardMarkup:
    options = ("پیش‌فرض", "قرمز", "آبی", "سبز", "زرد", "بنفش")
    builder = InlineKeyboardBuilder()
    for value in options:
        marker = "✓ " if value == current else ""
        builder.row(
            InlineKeyboardButton(
                text=f"{marker}{value}",
                callback_data=f"newgame:set_{kind}_color:{group_id}:{value}",
            )
        )
    builder.row(InlineKeyboardButton(text="بازگشت", callback_data=f"newgame:extras:{group_id}"))
    return builder.as_markup()


def new_game_extras_keyboard(
    group_id: int,
    auto_play: bool = False,
    turn_color: str = "پیش‌فرض",
    challenge_color: str = "پیش‌فرض",
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=f"بازی خودکار: {'فعال' if auto_play else 'غیرفعال'}",
            callback_data=f"newgame:toggle_auto:{group_id}",
        )
    )
    builder.row(
        InlineKeyboardButton(
            text=f"رنگ نوبت: {turn_color}",
            callback_data=f"newgame:turn_color:{group_id}",
        )
    )
    builder.row(
        InlineKeyboardButton(
            text=f"رنگ چالش: {challenge_color}",
            callback_data=f"newgame:challenge_color:{group_id}",
        )
    )
    builder.row(InlineKeyboardButton(text="بازگشت", callback_data=f"newgame:menu:{group_id}"))
    return builder.as_markup()


def lobby_keyboard_v2(game_key: str, scenario, players, reserves, is_host: bool = False, can_deal: bool = False, reserve_enabled: bool = True) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    buttons = []
    for seat in range(1, scenario.max_players + 1):
        item = next(((p, u) for p, u in players if p.seat == seat), None)
        if item:
            _, user = item
            name = (
                user.display_name
                or user.first_name
                or user.username
                or str(user.telegram_id)
            )[:12]
            label = f"{seat:02d} {name}"
        else:
            label = f"{seat:02d} —"
        buttons.append(InlineKeyboardButton(text=label, callback_data=f"lobby:seat:{game_key}:{seat}"))
    for i in range(0, len(buttons), 4):
        builder.row(*buttons[i:i+2])
    if reserve_enabled and len(players) >= scenario.max_players:
        builder.row(InlineKeyboardButton(text="رزرو", callback_data=f"lobby:reserve:{game_key}"))
    builder.row(
        InlineKeyboardButton(text="پیوستن", callback_data=f"game:join:{game_key}"),
        InlineKeyboardButton(text="ترک بازی", callback_data=f"game:leave:{game_key}"),
    )
    if can_deal:
        builder.row(InlineKeyboardButton(text="پخش نقش", callback_data=f"lobby:deal:{game_key}"))
    if is_host:
        builder.row(
            InlineKeyboardButton(text="مدیریت بازی", callback_data=f"gameadmin:lobby:{game_key}"),
            InlineKeyboardButton(text="مدیریت گروه", callback_data=f"groupadmin:lobby:{game_key}"),
        )
    return builder.as_markup()
