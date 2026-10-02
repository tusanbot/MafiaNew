from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from app.utils.text import tg_plain_name


def _back(builder: InlineKeyboardBuilder, callback_data: str = "menu:root") -> None:
    builder.row(InlineKeyboardButton(text="بازگشت", callback_data=callback_data))


def main_menu(show_admin: bool = False) -> InlineKeyboardMarkup:
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
    builder.row(InlineKeyboardButton(text="🏅 دستاوردها", callback_data="profile:achievements"))
    if show_admin:
        builder.row(InlineKeyboardButton(text="🛠 پنل مدیریت", callback_data="menu:admin"))
    _back(builder, "menu:root")
    return builder.as_markup()


def group_management_menu(back_callback: str = "menu:group_management") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="مدیریت بازی", callback_data="groupmgmt:games"))
    builder.row(InlineKeyboardButton(text="قفل گروه", callback_data="groupmgmt:locks"))
    _back(builder, back_callback)
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


def active_game_menu(group_id: int, back_callback: str | None = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="اطلاعات بازی", callback_data=f"gameadmin:info:{group_id}"))
    builder.row(InlineKeyboardButton(text="مدیریت بازیکنان", callback_data=f"gameadmin:players:{group_id}"))
    builder.row(InlineKeyboardButton(text="تنظیمات بازی", callback_data=f"gameadmin:features:{group_id}"))
    builder.row(InlineKeyboardButton(text="امکانات اضافی", callback_data=f"gameadmin:extras:{group_id}"))
    _back(builder, back_callback or f"groupmgmt:select:games:{group_id}")
    return builder.as_markup()


def player_management_menu(group_id: int, back_callback: str | None = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for key, label in (
        ("remove", "حذف بازیکن"),
        ("replace", "جایگزین"),
        ("silence", "سکوت"),
        ("extra_turn", "ترن اضافه"),
        ("kick", "کیک از بازی"),
        ("warning", "ثبت تذکر"),
        ("faceoff", "فیس آف"),
        ("slaughter", "سلاخی"),
        ("birthday", "تولد"),
    ):
        builder.row(InlineKeyboardButton(text=label, callback_data=f"gameadmin:player_action:{group_id}:{key}"))
    _back(builder, back_callback or f"gameadmin:active:{group_id}")
    return builder.as_markup()


def player_target_management_keyboard(group_id: int, action: str, players, *, only_alive: bool = False, only_dead: bool = False, only_reserve: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for player, user in players:
        if only_alive and (player.is_reserved or not player.alive):
            continue
        if only_dead and (player.is_reserved or player.alive or player.exit_type != "death"):
            continue
        if only_reserve and not player.is_reserved:
            continue
        name = user.display_name or user.first_name or user.username or str(user.telegram_id)
        status = " — رزرو" if player.is_reserved else (" — حذف‌شده" if not player.alive else "")
        builder.row(InlineKeyboardButton(
            text=f"{player.seat if not player.is_reserved else 'ر'} {name[:38]}{status}",
            callback_data=f"gameadmin:player_target:{group_id}:{action}:{user.id}",
        ))
    _back(builder, f"gameadmin:players:{group_id}")
    return builder.as_markup()


def player_target_action_keyboard(group_id: int, action: str, players) -> InlineKeyboardMarkup:
    return player_target_management_keyboard(group_id, action, players)


def player_faceoff_destination_keyboard(group_id: int, source_id: int, players) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for player, user in players:
        name = user.display_name or user.first_name or user.username or str(user.telegram_id)
        builder.row(InlineKeyboardButton(
            text=f"{player.seat}. {name[:38]}",
            callback_data=f"gameadmin:faceoff_to:{group_id}:{source_id}:{user.id}",
        ))
    _back(builder, f"gameadmin:players:{group_id}")
    return builder.as_markup()


def player_replace_destination_keyboard(group_id: int, source_id: int, reserves) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for player, user in reserves:
        name = user.display_name or user.first_name or user.username or str(user.telegram_id)
        builder.row(InlineKeyboardButton(
            text=f"رزرو {player.reserve_position} — {name[:38]}",
            callback_data=f"gameadmin:player_replace_to:{group_id}:{source_id}:{user.id}",
        ))
    _back(builder, f"gameadmin:players:{group_id}")
    return builder.as_markup()


def game_features_menu(
    group_id: int,
    challenge_enabled: bool = True,
    challenge_mode: str = "limited",
    next_host_enabled: bool = True,
    next_player_enabled: bool = True,
    next_auto_enabled: bool = False,
    auto_silence_warnings: bool = False,
    auto_kick_warnings: bool = False,
    turn_seconds: int = 120,
    challenge_seconds: int = 60,
    extra_challenge_seconds: int = 60,
    back_callback: str | None = None,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    challenge_label = "آزاد" if challenge_mode == "free" and challenge_enabled else "محدود" if challenge_enabled else "غیرفعال"
    challenge_mark = "🟢" if challenge_enabled else "⚪"
    builder.row(InlineKeyboardButton(
        text=f"{challenge_mark} چالش: {challenge_label}",
        callback_data=f"gameadmin:feature:{group_id}:challenge",
    ))
    builder.row(InlineKeyboardButton(
        text=f"{'🟢' if next_host_enabled else '⚪'} نکست گرداننده",
        callback_data=f"gameadmin:feature:{group_id}:next_host",
    ))
    builder.row(InlineKeyboardButton(
        text=f"{'🟢' if next_player_enabled else '⚪'} نکست بازیکن",
        callback_data=f"gameadmin:feature:{group_id}:next_player",
    ))
    builder.row(InlineKeyboardButton(
        text=f"{'🟢' if next_auto_enabled else '⚪'} نکست خودکار",
        callback_data=f"gameadmin:feature:{group_id}:next_auto",
    ))
    builder.row(InlineKeyboardButton(
        text=f"{'🟢' if auto_silence_warnings else '⚪'} سکوت خودکار با تذکر چهارم",
        callback_data=f"gameadmin:feature:{group_id}:auto_silence",
    ))
    builder.row(InlineKeyboardButton(
        text=f"{'🟢' if auto_kick_warnings else '⚪'} کیک خودکار با تذکر پنجم",
        callback_data=f"gameadmin:feature:{group_id}:auto_kick",
    ))
    builder.row(
        InlineKeyboardButton(text=f"🗣 نوبت {turn_seconds // 60:02d}:{turn_seconds % 60:02d}", callback_data=f"gameadmin:time:{group_id}:turn"),
        InlineKeyboardButton(text=f"🤏🏻 چالش {challenge_seconds // 60:02d}:{challenge_seconds % 60:02d}", callback_data=f"gameadmin:time:{group_id}:challenge"),
    )
    builder.row(InlineKeyboardButton(
        text=f"➕ چالش اضافه {extra_challenge_seconds // 60:02d}:{extra_challenge_seconds % 60:02d}",
        callback_data=f"gameadmin:time:{group_id}:extra_challenge",
    ))
    builder.row(InlineKeyboardButton(text="اتمام بازی", callback_data=f"gameadmin:feature:{group_id}:finish"))
    builder.row(InlineKeyboardButton(text="لغو واقعی بازی", callback_data=f"gameadmin:feature:{group_id}:cancel"))
    builder.row(InlineKeyboardButton(text="مدیریت اموجی‌ها", callback_data=f"gameadmin:emoji:{group_id}"))
    _back(builder, back_callback or f"gameadmin:active:{group_id}")
    return builder.as_markup()


def emoji_management_menu(group_id: int, settings: dict, back_callback: str | None = None) -> InlineKeyboardMarkup:
    labels = {
        "death": "مرگ",
        "kick": "کیک",
        "slaughter": "سلاخی",
        "challenge": "چالش",
        "silence": "سکوت",
        "extra_turn": "ترن اضافه",
        "warning": "تعداد تذکر",
    }
    builder = InlineKeyboardBuilder()
    for key, label in labels.items():
        builder.row(InlineKeyboardButton(
            text=f"{'🟢' if settings.get(key, True) else '⚪'} {label}",
            callback_data=f"gameadmin:emoji_toggle:{group_id}:{key}",
        ))
    _back(builder, back_callback or f"gameadmin:features:{group_id}")
    return builder.as_markup()


def game_extras_menu(group_id: int, auto_play: bool = False, turn_color: str = "پیش‌فرض", challenge_color: str = "پیش‌فرض", turn_color_enabled: bool = True, back_callback: str | None = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text=f"بازی خودکار: {'فعال' if auto_play else 'غیرفعال'}",
        callback_data=f"gameadmin:extra:{group_id}:auto_play",
    ))
    builder.row(InlineKeyboardButton(
        text=f"تفکیک رنگ نوبت/چالش: {'فعال' if turn_color_enabled else 'غیرفعال'}",
        callback_data=f"gameadmin:extra:{group_id}:turn_color_enabled",
    ))
    builder.row(InlineKeyboardButton(text=f"تغییر رنگ نوبت: {turn_color}", callback_data=f"gameadmin:extra:{group_id}:turn_color"))
    builder.row(InlineKeyboardButton(text=f"تغییر رنگ چالش: {challenge_color}", callback_data=f"gameadmin:extra:{group_id}:challenge_color"))
    _back(builder, back_callback or f"gameadmin:active:{group_id}")
    return builder.as_markup()


def cancel_game_keyboard(group_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="تأیید لغو بازی", callback_data=f"gameadmin:cancel_confirm:{group_id}"),
        InlineKeyboardButton(text="انصراف", callback_data=f"gameadmin:features:{group_id}"),
    )
    return builder.as_markup()


def finish_game_keyboard(group_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for key, label in (
        ("citizen", "برد شهروند"),
        ("mafia", "برد مافیا"),
        ("independent", "برد مستقل"),
        ("citizen_independent", "برد شهروند/مستقل"),
        ("draw", "مساوی"),
    ):
        builder.row(InlineKeyboardButton(text=label, callback_data=f"gameadmin:finish_result:{group_id}:{key}"))
    _back(builder, f"gameadmin:features:{group_id}")
    return builder.as_markup()


def finish_game_confirm_keyboard(group_id: int, winner: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="تأیید نتیجه", callback_data=f"gameadmin:finish_confirm:{group_id}:{winner}"))
    builder.row(InlineKeyboardButton(text="تغییر برنده", callback_data=f"gameadmin:feature:{group_id}:finish"))
    return builder.as_markup()


def game_result_keyboard(group_id: int, game_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="تاریخچه بازی‌ها", callback_data=f"groupgame:history:{group_id}"))
    builder.row(
        InlineKeyboardButton(text="آمار", callback_data=f"gameresult:stats:{game_id}"),
        InlineKeyboardButton(text="رتبه‌بندی", callback_data="ranking:players"),
    )
    builder.row(InlineKeyboardButton(text="اتفاقات بازی", callback_data=f"gameresult:events:{game_id}"))
    return builder.as_markup()


def bot_settings_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="⚙️ تنظیمات عمومی", callback_data="botsettings:general"))
    builder.row(InlineKeyboardButton(text="🔔 تنظیمات اعلان ها", callback_data="botsettings:notifications"))
    _back(builder)
    return builder.as_markup()

def notification_settings_menu(user) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    items = (
        ("notify_game_result", "نتیجه بازی"),
        ("notify_achievements", "دستاوردهای جدید"),
        ("notify_rank_changes", "تغییر رتبه"),
    )
    for key, label in items:
        builder.row(InlineKeyboardButton(
            text=f"{'✅' if getattr(user, key) else '❌'} {label}",
            callback_data=f"notify:toggle:{key}",
        ))
    _back(builder, "menu:bot_settings")
    return builder.as_markup()

def profile_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="امتیازات", callback_data="profile:score"),
        InlineKeyboardButton(text="رتبه", callback_data="profile:rank"),
    )
    builder.row(
        InlineKeyboardButton(text="تغییر نام", callback_data="profile:name"),
        InlineKeyboardButton(text="تگ‌ها", callback_data="profile:tags"),
    )
    builder.row(InlineKeyboardButton(text="🏅 دستاوردها", callback_data="profile:achievements"))
    _back(builder)
    return builder.as_markup()

def scenario_management_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="➕ ایجاد سناریو", callback_data="scenario_admin:create"))
    builder.row(InlineKeyboardButton(text="✏️ ویرایش سناریو", callback_data="scenario_admin:edit"))
    builder.row(InlineKeyboardButton(text="🗑 حذف سناریو", callback_data="scenario_admin:delete"))
    _back(builder)
    return builder.as_markup()

def scenario_admin_list_keyboard(scenarios, action: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for scenario in scenarios:
        state = "فعال" if scenario.enabled else "غیرفعال"
        builder.row(InlineKeyboardButton(
            text=f"{scenario.name_fa} — {state}",
            callback_data=f"scenario_admin:{action}:{scenario.id}",
        ))
    _back(builder, "menu:scenarios")
    return builder.as_markup()

def scenario_role_keyboard(roles, selected_ids: set[int] | dict[int, int] | None = None, action: str = "create") -> InlineKeyboardMarkup:
    selected_ids = selected_ids or set()
    counts = selected_ids if isinstance(selected_ids, dict) else {x: 1 for x in selected_ids}
    builder = InlineKeyboardBuilder()
    for i in range(0, len(roles), 2):
        row = []
        for role in roles[i:i+2]:
            count = int(counts.get(role.id, 0))
            mark = "⬜" if count == 0 else f"✅×{count}"
            row.append(InlineKeyboardButton(text=f"{mark} {role.name_fa[:20]}", callback_data=f"scenario_admin:{action}:role:{role.id}"))
        builder.row(*row)
    builder.row(InlineKeyboardButton(text="ادامه", callback_data=f"scenario_admin:{action}:roles_done"))
    builder.row(InlineKeyboardButton(text="لغو", callback_data="scenario_admin:cancel"))
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


def player_target_keyboard(prefix: str, game_key: str, players, exclude_user_id: int | None = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for player, user, *rest in players:
        if exclude_user_id is not None and user.id == exclude_user_id:
            continue
        builder.row(InlineKeyboardButton(
            text=f"{player.seat}. {tg_plain_name(user.display_name or user.first_name)}",
            callback_data=f"{prefix}:{game_key}:{user.id}",
        ))
    return builder.as_markup()


def night_action_keyboard(
    game_key: str,
    action_type: str,
    players,
    actor_user_id: int | None = None,
) -> InlineKeyboardMarkup:
    exclude = actor_user_id if action_type == "mafia_kill" else None
    return player_target_keyboard(f"night:{action_type}", game_key, players, exclude_user_id=exclude)


def vote_keyboard(game_key: str, players) -> InlineKeyboardMarkup:
    return player_target_keyboard("vote", game_key, players)


def day_keyboard(game_key: str, players=None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🗳 رأی‌گیری", callback_data=f"day:vote:{game_key}"),
        InlineKeyboardButton(text="🌙 شروع فاز شب", callback_data=f"day:night:{game_key}"),
    )
    builder.row(InlineKeyboardButton(text="🏁 اتمام بازی", callback_data=f"day:finish:{game_key}"))
    return builder.as_markup()



def leader_settings_keyboard(game_key: str, game, leader_selected: bool = False) -> InlineKeyboardMarkup:
    """Setup menu: before leader selection only leader/settings are visible;
    after selection the same menu exposes start-round."""
    builder = InlineKeyboardBuilder()
    if not leader_selected:
        builder.row(InlineKeyboardButton(text="👑 انتخاب سردست", callback_data=f"leader:menu:{game_key}"))
        builder.row(InlineKeyboardButton(text="⚙️ تنظیمات بازی", callback_data=f"round:settings:{game_key}"))
        return builder.as_markup()

    builder.row(InlineKeyboardButton(text="👑 انتخاب سردست", callback_data=f"leader:menu:{game_key}"))
    builder.row(InlineKeyboardButton(text="⚙️ تنظیمات بازی", callback_data=f"round:settings:{game_key}"))
    builder.row(InlineKeyboardButton(text="▶️ شروع دور", callback_data=f"round:start:{game_key}"))
    return builder.as_markup()


def leader_choice_keyboard(game_key: str, players) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="✋ انتخاب دستی", callback_data=f"leader:manual:{game_key}"))
    builder.row(InlineKeyboardButton(text="🎲 انتخاب خودکار", callback_data=f"leader:auto:{game_key}"))
    builder.row(InlineKeyboardButton(text="🔙 بازگشت", callback_data=f"leader:back:{game_key}"))
    return builder.as_markup()


def leader_players_keyboard(game_key: str, players) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for _player, user, *_ in players:
        name = tg_plain_name(user.display_name or user.first_name or user.username or str(user.telegram_id))
        builder.row(InlineKeyboardButton(
            text=f"👤 {name[:48]}",
            callback_data=f"leader:pick:{game_key}:{user.id}",
        ))
    builder.row(InlineKeyboardButton(text="🔙 بازگشت", callback_data=f"leader:menu:{game_key}"))
    return builder.as_markup()

def continue_night_keyboard(game_key: str, night_locked: bool = False, chat_locked: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="ارسال اقدامات شب", callback_data=f"night:resolve:{game_key}"))
    builder.row(
        InlineKeyboardButton(
            text=f"قفل شب: {'فعال' if night_locked else 'غیرفعال'}",
            callback_data=f"night:lock:{game_key}:night_lock",
        ),
        InlineKeyboardButton(
            text=f"قفل بازی: {'فعال' if chat_locked else 'غیرفعال'}",
            callback_data=f"night:lock:{game_key}:chat_lock",
        ),
    )
    builder.row(InlineKeyboardButton(text="شروع روز", callback_data=f"night:start_day:{game_key}"))
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


def day_turn_keyboard(
    game_key: str,
    is_current_speaker: bool = False,
    challenge_enabled: bool = True,
    turn_color_enabled: bool = True,
    turn_color: str = "پیش‌فرض",
    challenge_color: str = "پیش‌فرض",
    challenge_emoji_enabled: bool = True,
    allow_challenge: bool = True,
    challenge_requests=None,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for event, data in (challenge_requests or []):
        name = tg_plain_name(data.get("requester_name", "بازیکن"))
        builder.row(InlineKeyboardButton(
            text=f"🤏🏻 {name}",
            callback_data=f"challenge:grant:{game_key}:{event.id}",
        ))
    if challenge_enabled and allow_challenge:
        mark = ({"سبز": "🟢", "آبی": "🔵", "بنفش": "🟣", "قرمز": "🔴", "زرد": "🟡", "طلایی": "🟡"}.get(challenge_color, "") if turn_color_enabled else "") if challenge_emoji_enabled else ""
        builder.row(InlineKeyboardButton(
            text=f"{mark} 🤏🏻 درخواست چالش".strip(),
            callback_data=f"turn:request_challenge:{game_key}",
        ))
    if is_current_speaker:
        mark = {"سبز": "🟢", "آبی": "🔵", "بنفش": "🟣", "قرمز": "🔴", "زرد": "🟡", "طلایی": "🟡"}.get(turn_color, "") if turn_color_enabled else ""
        builder.row(InlineKeyboardButton(
            text=f"{mark} ⏩ نکست ترن".strip(),
            callback_data=f"turn:next:{game_key}",
        ))
    return builder.as_markup()


def voting_setup_keyboard(game_key: str, pre_delay: int = 10, vote_seconds: int = 10, voting_mode: str = "manual") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=f"⏳ انتظار قبل از رای: {pre_delay} ثانیه", callback_data=f"votingset:delay:{game_key}"))
    builder.row(InlineKeyboardButton(text=f"⏱ زمان هر رای: {vote_seconds} ثانیه", callback_data=f"votingset:duration:{game_key}"))
    builder.row(InlineKeyboardButton(text=f"نوع رای گیری: {'خودکار' if voting_mode == 'auto' else 'دستی'}", callback_data=f"votingset:mode:{game_key}"))
    builder.row(InlineKeyboardButton(text="گرفتن حق رای", callback_data=f"votingset:revoke:{game_key}"))
    builder.row(InlineKeyboardButton(text="شروع رای ۱", callback_data=f"vote:start1:{game_key}"))
    return builder.as_markup()


def voting_delay_keyboard(game_key: str, current: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for value in (0, 5, 10, 15, 30):
        builder.row(InlineKeyboardButton(text=f"{'✓ ' if value == current else ''}{value} ثانیه", callback_data=f"votingset:set_delay:{game_key}:{value}"))
    _back(builder, f"votingset:menu:{game_key}")
    return builder.as_markup()


def voting_duration_keyboard(game_key: str, current: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for value in (5, 10, 15, 20, 30, 60, 90):
        builder.row(InlineKeyboardButton(text=f"{'✓ ' if value == current else ''}{value} ثانیه", callback_data=f"votingset:set_duration:{game_key}:{value}"))
    _back(builder, f"votingset:menu:{game_key}")
    return builder.as_markup()


def voting_mode_keyboard(game_key: str, current: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=f"{'✓ ' if current == 'manual' else ''}دستی", callback_data=f"votingset:set_mode:{game_key}:manual"))
    builder.row(InlineKeyboardButton(text=f"{'✓ ' if current == 'auto' else ''}خودکار", callback_data=f"votingset:set_mode:{game_key}:auto"))
    _back(builder, f"votingset:menu:{game_key}")
    return builder.as_markup()


def vote_rights_keyboard(game_key: str, players, revoked_ids: set[int] | None = None) -> InlineKeyboardMarkup:
    revoked_ids = revoked_ids or set()
    builder = InlineKeyboardBuilder()
    for player, user, *_ in players:
        if not player.alive:
            continue
        name = tg_plain_name(user.display_name or user.first_name or user.username or str(user.telegram_id))
        mark = "🚫" if user.id in revoked_ids else "🗳"
        builder.row(InlineKeyboardButton(text=f"{mark} {name}", callback_data=f"votingset:revoke_target:{game_key}:{user.id}"))
    _back(builder, f"votingset:menu:{game_key}")
    return builder.as_markup()


def vote1_target_keyboard(game_key: str, target_user_id: int, voter_count: int = 0) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=f"🗳 رای میدم", callback_data=f"vote1:cast:{game_key}:{target_user_id}"))
    return builder.as_markup()


def vote1_complete_keyboard(game_key: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="اتمام رای گیری", callback_data=f"vote1:finish:{game_key}"))
    return builder.as_markup()


def defense_selection_keyboard(game_key: str, players, selected_ids: set[int] | None = None) -> InlineKeyboardMarkup:
    selected_ids = selected_ids or set()
    builder = InlineKeyboardBuilder()
    for player, user, *_ in players:
        if player.alive:
            name = tg_plain_name(user.display_name or user.first_name or user.username or str(user.telegram_id))
            mark = "✅" if user.id in selected_ids else "⬜"
            builder.row(InlineKeyboardButton(text=f"{mark} {name}", callback_data=f"vote2:select:{game_key}:{user.id}"))
    builder.row(InlineKeyboardButton(text="شروع رای ۲", callback_data=f"vote2:start:{game_key}"))
    return builder.as_markup()


def vote_right_confirm_keyboard(game_key: str, user_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="تأیید گرفتن حق رای", callback_data=f"votingset:confirm_revoke:{game_key}:{user_id}"),
        InlineKeyboardButton(text="انصراف", callback_data=f"votingset:revoke:{game_key}"),
    )
    return builder.as_markup()


def vote2_result_keyboard(game_key: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="شروع فاز شب", callback_data=f"day:night:{game_key}"))
    builder.row(InlineKeyboardButton(text="پایان بازی", callback_data=f"day:finish:{game_key}"))
    return builder.as_markup()

def vote2_setup_keyboard(game_key: str, selection_mode: str = "manual") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text=f"نوع رای گیری دوم: {'خودکار' if selection_mode == 'auto' else 'دستی'}",
        callback_data=f"vote2:mode:{game_key}",
    ))
    builder.row(InlineKeyboardButton(
        text="انتخاب بازیکنان برای دفاع",
        callback_data=f"vote2:choose:{game_key}",
    ))
    builder.row(InlineKeyboardButton(text="شروع رای ۲", callback_data=f"vote2:begin:{game_key}"))
    return builder.as_markup()


def vote2_target_keyboard(game_key: str, target_user_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🗳 رای میدم", callback_data=f"vote2:cast:{game_key}:{target_user_id}"))
    return builder.as_markup()


def vote2_next_keyboard(game_key: str, final: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if final:
        builder.row(InlineKeyboardButton(text="اتمام رای گیری", callback_data=f"vote2:finish:{game_key}"))
    else:
        builder.row(InlineKeyboardButton(text="بازیکن بعدی", callback_data=f"vote2:next:{game_key}"))
    return builder.as_markup()


def vote2_complete_keyboard(game_key: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="اتمام رای گیری", callback_data=f"vote2:finish:{game_key}"))
    return builder.as_markup()


def challenge_requests_keyboard(game_key: str, requests) -> InlineKeyboardMarkup:
    return day_turn_keyboard(game_key, False, True, False, challenge_requests=requests)


def challenge_placement_keyboard(game_key: str, event_id: int, requester_name: str | None = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if requester_name:
        builder.row(InlineKeyboardButton(
            text=f"👤 {tg_plain_name(requester_name)}",
            callback_data=f"challenge:select:{game_key}:{event_id}",
        ))
    else:
        builder.row(InlineKeyboardButton(
            text="انتخاب بازیکن",
            callback_data=f"challenge:select:{game_key}:{event_id}",
        ))
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
        builder.row(InlineKeyboardButton(text=tg_plain_name(name[:60]), callback_data=f"newgame:sethost:{group_id}:{user.id}"))
    builder.row(InlineKeyboardButton(text="بازگشت", callback_data=f"newgame:menu:{group_id}"))
    return builder.as_markup()


def new_game_settings_keyboard(
    group_id: int,
    challenge_enabled: bool = True,
    next_host_enabled: bool = True,
    next_player_enabled: bool = True,
    next_auto_enabled: bool = False,
    auto_play: bool = False,
    turn_seconds: int = 120,
    challenge_seconds: int = 60,
    extra_challenge_seconds: int = 60,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text=f"🤏🏻 چالش: {'فعال' if challenge_enabled else 'غیرفعال'}",
        callback_data=f"newgame:toggle_challenge:{group_id}",
    ))
    builder.row(
        InlineKeyboardButton(
            text=f"🎛 نکست گرداننده: {'فعال' if next_host_enabled else 'غیرفعال'}",
            callback_data=f"newgame:toggle_host_next:{group_id}",
        ),
        InlineKeyboardButton(
            text=f"⏭ نکست بازیکن: {'فعال' if next_player_enabled else 'غیرفعال'}",
            callback_data=f"newgame:toggle_player_next:{group_id}",
        ),
    )
    builder.row(InlineKeyboardButton(
        text=f"⏱ نکست خودکار: {'فعال' if next_auto_enabled else 'غیرفعال'}",
        callback_data=f"newgame:toggle_auto_next:{group_id}",
    ))
    builder.row(InlineKeyboardButton(
        text=f"🤖 بازی خودکار: {'فعال' if auto_play else 'غیرفعال'}",
        callback_data=f"newgame:toggle_auto:{group_id}",
    ))
    builder.row(
        InlineKeyboardButton(text=f"🗣 نوبت: {turn_seconds // 60:02d}:{turn_seconds % 60:02d}", callback_data=f"newgame:time:{group_id}:turn"),
        InlineKeyboardButton(text=f"🤏🏻 چالش: {challenge_seconds // 60:02d}:{challenge_seconds % 60:02d}", callback_data=f"newgame:time:{group_id}:challenge"),
    )
    builder.row(InlineKeyboardButton(
        text=f"➕ چالش اضافه: {extra_challenge_seconds // 60:02d}:{extra_challenge_seconds % 60:02d}",
        callback_data=f"newgame:time:{group_id}:extra_challenge",
    ))
    builder.row(InlineKeyboardButton(text="بازگشت", callback_data=f"newgame:menu:{group_id}"))
    return builder.as_markup()

def duration_keyboard(prefix: str, group_id: int, kind: str, current: int, back_callback: str) -> InlineKeyboardMarkup:
    options = (30, 60, 90, 120, 180, 240, 300)
    builder = InlineKeyboardBuilder()
    for value in options:
        marker = "✓ " if value == current else ""
        builder.row(InlineKeyboardButton(
            text=f"{marker}{value // 60:02d}:{value % 60:02d}",
            callback_data=f"{prefix}:set_time:{group_id}:{kind}:{value}",
        ))
    _back(builder, back_callback)
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
    turn_color: str = "پیش‌فرض",
    challenge_color: str = "پیش‌فرض",
    emoji_enabled: bool = True,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text=f"🎨 رنگ نوبت: {turn_color}",
        callback_data=f"newgame:turn_color:{group_id}",
    ))
    builder.row(InlineKeyboardButton(
        text=f"🤏🏻 رنگ چالش: {challenge_color}",
        callback_data=f"newgame:challenge_color:{group_id}",
    ))
    builder.row(InlineKeyboardButton(
        text=f"🙂 اموجی‌های وضعیت: {'فعال' if emoji_enabled else 'غیرفعال'}",
        callback_data=f"newgame:emoji:{group_id}",
    ))
    builder.row(InlineKeyboardButton(text="بازگشت", callback_data=f"newgame:menu:{group_id}"))
    return builder.as_markup()


def new_game_emoji_menu(group_id: int, settings: dict) -> InlineKeyboardMarkup:
    labels = {
        "death": "مرگ",
        "kick": "کیک",
        "slaughter": "سلاخی",
        "challenge": "چالش",
        "silence": "سکوت",
        "extra_turn": "ترن اضافه",
        "warning": "تعداد تذکر",
    }
    builder = InlineKeyboardBuilder()
    for key, label in labels.items():
        builder.row(InlineKeyboardButton(
            text=f"{'🟢' if settings.get(key, True) else '⚪'} {label}",
            callback_data=f"newgame:emoji_toggle:{group_id}:{key}",
        ))
    _back(builder, f"newgame:extras:{group_id}")
    return builder.as_markup()

def lobby_keyboard_v2(game_key: str, scenario, players, reserves, is_host: bool = False, can_deal: bool = False, reserve_enabled: bool = True, training_url: str | None = None, telegram_training_url: str | None = None) -> InlineKeyboardMarkup:
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
        builder.row(*buttons[i:i+4])
    if reserve_enabled and len(players) >= scenario.max_players:
        builder.row(InlineKeyboardButton(text="رزرو", callback_data=f"lobby:reserve:{game_key}"))
    builder.row(
        InlineKeyboardButton(text="پیوستن", callback_data=f"game:join:{game_key}"),
        InlineKeyboardButton(text="ترک بازی", callback_data=f"game:leave:{game_key}"),
    )
    if can_deal:
        builder.row(InlineKeyboardButton(text="پخش نقش", callback_data=f"lobby:deal:{game_key}"))
    if training_url or telegram_training_url:
        buttons = []
        if training_url:
            buttons.append(InlineKeyboardButton(text="📚 آموزش سناریو", url=training_url))
        if telegram_training_url:
            buttons.append(InlineKeyboardButton(text="📣 آموزش در تلگرام", url=telegram_training_url))
        builder.row(*buttons)
    if is_host:
        builder.row(
            InlineKeyboardButton(text="مدیریت بازی", callback_data=f"gameadmin:lobby:{game_key}"),
            InlineKeyboardButton(text="مدیریت گروه", callback_data=f"groupadmin:lobby:{game_key}"),
        )
    return builder.as_markup()


def admin_panel_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="📊 داشبورد", callback_data="admin:dashboard"))
    builder.row(InlineKeyboardButton(text="👥 گروه‌ها", callback_data="admin:groups"))
    builder.row(InlineKeyboardButton(text="🎭 سناریوها", callback_data="admin:scenarios"))
    builder.row(InlineKeyboardButton(text="🎮 بازی‌های اخیر", callback_data="admin:games"))
    builder.row(InlineKeyboardButton(text="⚙️ تنظیمات ربات", callback_data="admin:settings"))
    _back(builder, "menu:root")
    return builder.as_markup()


def admin_scenario_keyboard(scenarios) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for scenario in scenarios:
        state = "فعال" if scenario.enabled else "غیرفعال"
        builder.row(InlineKeyboardButton(
            text=f"{scenario.name_fa}: {state}",
            callback_data=f"admin:scenario_toggle:{scenario.id}",
        ))
    _back(builder, "admin:dashboard")
    return builder.as_markup()

def scenario_challenge_keyboard(action: str = "create", include_unchanged: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🤏🏻 چالش محدود", callback_data=f"scenario_admin:{action}:challenge:limited"),
        InlineKeyboardButton(text="🤏🏻 چالش آزاد", callback_data=f"scenario_admin:{action}:challenge:free"),
    )
    builder.row(InlineKeyboardButton(text="🚫 بدون چالش", callback_data=f"scenario_admin:{action}:challenge:off"))
    if include_unchanged:
        builder.row(InlineKeyboardButton(text="↩️ بدون تغییر", callback_data=f"scenario_admin:{action}:challenge:unchanged"))
    builder.row(InlineKeyboardButton(text="لغو", callback_data="scenario_admin:cancel"))
    return builder.as_markup()

def scenario_delete_confirm_keyboard(scenario_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🗑 بله، حذف شود", callback_data=f"scenario_admin:delete_confirm:{scenario_id}"),
        InlineKeyboardButton(text="انصراف", callback_data="menu:scenarios"),
    )
    return builder.as_markup()
