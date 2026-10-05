from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, CopyTextButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from app.utils.text import tg_plain_name
from app.utils.custom_emoji import DEFAULT_EMOJIS, normalize_emoji_map

_BUTTON_EMOJI_RULES = (
    ("مدیریت بازی فعال", "🎮"), ("مدیریت گروه", "👥"), ("تنظیمات و قفل", "🔐"),
    ("تنظیمات عمومی", "⚙️"), ("تنظیمات اعلان", "🔔"), ("تنظیمات ربات", "⚙️"),
    ("پروفایل", "👤"), ("رتبه", "🏆"), ("امتیازات", "💰"), ("تغییر نام", "✏️"),
    ("تگ", "🏷️"), ("دستاورد", "🏅"), ("پنل مدیریت", "🛠️"), ("اطلاعات بازی", "ℹ️"),
    ("مدیریت بازیکنان", "👥"), ("تنظیمات بازی", "⚙️"), ("امکانات اضافی", "✨"),
    ("تاریخچه", "📚"), ("لغو بازی", "❌"), ("اتمام بازی", "🏁"), ("اتفاقات بازی", "📜"),
    ("ثبت اتفاق", "📝"), ("مدیریت اموجی", "🎨"), ("بازگشت", "↩️"), ("بستن", "✖️"), ("ادامه", "➡️"),
    ("لغو", "❌"), ("پیوستن", "🎮"), ("ترک بازی", "🚪"), ("شروع بازی", "▶️"),
    ("شروع دور", "▶️"), ("انتخاب سردست", "👑"), ("انتخاب دستی", "✋"),
    ("انتخاب خودکار", "🎲"), ("رای", "🗳️"), ("چالش", "🤏🏻"), ("شب", "🌙"),
    ("روز", "☀️"), ("بازیکن بعدی", "➡️"), ("برد", "🏆"), ("مساوی", "⚖️"),
    ("تأیید", "✅"), ("حذف", "🗑️"), ("ایجاد", "➕"), ("ویرایش", "✏️"),
)

def _decorate_button_text(value: str) -> str:
    text = str(value or "")
    if any(0x1F000 <= ord(ch) <= 0x1FAFF or 0x2300 <= ord(ch) <= 0x27BF for ch in text[:4]):
        return text
    for needle, emoji in _BUTTON_EMOJI_RULES:
        if needle in text:
            return f"{emoji} {text}"
    return text

_OriginalInlineKeyboardButton = InlineKeyboardButton
def InlineKeyboardButton(*args, **kwargs):
    if "text" in kwargs:
        kwargs["text"] = _decorate_button_text(kwargs["text"])
    elif args:
        args = (_decorate_button_text(args[0]), *args[1:])
    return _OriginalInlineKeyboardButton(*args, **kwargs)


def _back(builder: InlineKeyboardBuilder, callback_data: str = "menu:root") -> None:
    builder.row(InlineKeyboardButton(text="بازگشت", callback_data=callback_data))


def main_menu(show_admin: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🎮 مدیریت بازی فعال", callback_data="menu:active_game"))
    builder.row(InlineKeyboardButton(text="👥 مدیریت گروه", callback_data="menu:group_management"))
    builder.row(InlineKeyboardButton(text="🏆 تورنمنت‌ها", callback_data="menu:tournaments"))
    if show_admin:
        builder.row(InlineKeyboardButton(text="🎭 سناریوها", callback_data="menu:scenarios"))
    builder.row(InlineKeyboardButton(text="⚙️ تنظیمات ربات", callback_data="menu:bot_settings"))
    builder.row(
        InlineKeyboardButton(text="👤 پروفایل", callback_data="menu:profile"),
        InlineKeyboardButton(text="🏆 رتبه‌بندی", callback_data="menu:ranking"),
    )
    if show_admin:
        builder.row(InlineKeyboardButton(text="🛠 پنل مدیریت", callback_data="menu:admin"))
    builder.row(InlineKeyboardButton(text="بستن", callback_data="menu:close"))
    return builder.as_markup()


def group_management_menu(back_callback: str = "menu:root") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🎮 مدیریت بازی‌های گروه", callback_data="groupmgmt:games"))
    builder.row(
        InlineKeyboardButton(text="⚙️ تنظیمات پایه بازی", callback_data="groupmgmt:defaults"),
        InlineKeyboardButton(text="👥 تنظیمات بازیکنان", callback_data="groupmgmt:players"),
    )
    builder.row(
        InlineKeyboardButton(text="🔔 اعلان‌های گروه", callback_data="groupmgmt:notifications"),
        InlineKeyboardButton(text="🔒 قفل‌های گروه", callback_data="groupmgmt:locks"),
    )
    builder.row(
        InlineKeyboardButton(text="🏆 مدیریت دستاوردها", callback_data="groupmgmt:achievements"),
        InlineKeyboardButton(text="🏷️ مدیریت تگ‌ها", callback_data="groupmgmt:tags"),
    )
    builder.row(InlineKeyboardButton(text="🏆 تورنمنت‌ها", callback_data="groupmgmt:tournaments"))
    builder.row(InlineKeyboardButton(text="🎂 ثبت تاریخ تولد بازیکن", callback_data="groupmgmt:birthday"))
    builder.row(InlineKeyboardButton(text="🎬 ویدیوی لابی", callback_data="groupmgmt:lobby_media"))
    builder.row(InlineKeyboardButton(text="📨 دعوت به بازی", callback_data="groupmgmt:invitation"))
    _back(builder, back_callback)
    return builder.as_markup()


def group_default_settings_menu(group_id: int, settings) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text=f"🤖 بازی خودکار: {'✅' if settings.default_auto_play else '❌'}",
        callback_data=f"groupdefaults:toggle:{group_id}:default_auto_play",
    ))
    builder.row(InlineKeyboardButton(
        text=f"🤏 چالش: {'✅' if settings.default_challenge_enabled else '❌'}",
        callback_data=f"groupdefaults:toggle:{group_id}:default_challenge_enabled",
    ))
    builder.row(
        InlineKeyboardButton(text=f"⏱ نوبت: {settings.default_turn_seconds}s", callback_data=f"groupdefaults:time:{group_id}:turn"),
        InlineKeyboardButton(text=f"🤏 زمان چالش: {settings.default_challenge_seconds}s", callback_data=f"groupdefaults:time:{group_id}:challenge"),
    )
    builder.row(InlineKeyboardButton(
        text=f"➕ چالش اضافه: {settings.default_extra_challenge_seconds}s",
        callback_data=f"groupdefaults:time:{group_id}:extra_challenge",
    ))
    builder.row(
        InlineKeyboardButton(text=f"⏭ نکست گرداننده: {'✅' if settings.default_next_host_enabled else '❌'}", callback_data=f"groupdefaults:toggle:{group_id}:default_next_host_enabled"),
        InlineKeyboardButton(text=f"⏭ نکست بازیکن: {'✅' if settings.default_next_player_enabled else '❌'}", callback_data=f"groupdefaults:toggle:{group_id}:default_next_player_enabled"),
    )
    builder.row(InlineKeyboardButton(
        text=f"🔄 نکست خودکار: {'✅' if settings.default_next_auto_enabled else '❌'}",
        callback_data=f"groupdefaults:toggle:{group_id}:default_next_auto_enabled",
    ))
    builder.row(InlineKeyboardButton(
        text=f"🪑 رزرو پیش‌فرض: {'✅' if settings.default_reserve_enabled else '❌'}",
        callback_data=f"groupdefaults:toggle:{group_id}:default_reserve_enabled",
    ))
    builder.row(InlineKeyboardButton(text="🎨 رنگ‌ها و اموجی‌ها", callback_data=f"groupdefaults:visual:{group_id}"))
    builder.row(InlineKeyboardButton(text="🗳 تنظیمات رأی‌گیری", callback_data=f"groupdefaults:voting:{group_id}"))
    builder.row(InlineKeyboardButton(text="🎭 سناریوی پیش‌فرض", callback_data=f"groupdefaults:scenario:{group_id}"))
    _back(builder, "menu:group_management")
    return builder.as_markup()


def group_visual_settings_menu(group_id: int, settings) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text=f"🎨 رنگ نوبت: {settings.default_turn_color}",
        callback_data=f"groupdefaults:color:{group_id}:turn",
    ))
    builder.row(InlineKeyboardButton(
        text=f"🎨 رنگ چالش: {settings.default_challenge_color}",
        callback_data=f"groupdefaults:color:{group_id}:challenge",
    ))
    builder.row(InlineKeyboardButton(
        text=f"🟢 نمایش رنگ نوبت: {'✅' if settings.default_turn_color_enabled else '❌'}",
        callback_data=f"groupdefaults:toggle:{group_id}:default_turn_color_enabled",
    ))
    builder.row(InlineKeyboardButton(
        text=f"✨ اموجی‌های متحرک: {'فعال' if settings.custom_emoji else 'خاموش'}",
        callback_data=f"groupdefaults:emoji_menu:{group_id}",
    ))
    _back(builder, "groupmgmt:defaults")
    return builder.as_markup()


def group_custom_emoji_menu(group_id: int, settings) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text=f"✨ اموجی‌های متحرک: {'فعال' if settings.custom_emoji else 'خاموش'}",
        callback_data=f"groupdefaults:emoji_toggle:{group_id}",
    ))
    builder.row(
        InlineKeyboardButton(text="🎮 بازی و روند بازی", callback_data=f"groupdefaults:emoji_section:{group_id}:game"),
        InlineKeyboardButton(text="🏆 دستاوردها", callback_data=f"groupdefaults:emoji_section:{group_id}:achievement"),
    )
    builder.row(InlineKeyboardButton(
        text="🏷️ تگ‌ها",
        callback_data=f"groupdefaults:emoji_section:{group_id}:tag",
    ))
    builder.row(InlineKeyboardButton(
        text="🧹 پاک‌کردن اموجی‌های بازی",
        callback_data=f"groupdefaults:emoji_clear:{group_id}",
    ))
    _back(builder, f"groupmgmt:select:defaults:{group_id}")
    return builder.as_markup()


def group_game_emoji_menu(group_id: int, settings) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    mapping = normalize_emoji_map(getattr(settings, "custom_emoji_ids", "{}"))
    labels = {
        "turn":"⏩ نوبت", "challenge":"🤏🏻 چالش", "vote":"🗳️ رأی‌گیری",
        "defense":"🛡️ دفاع", "silence":"🔇 سکوت", "extra_turn":"➕ ترن اضافه",
        "warning":"⚠️ تذکر", "death":"💀 حذف/مرگ", "kick":"⛔ کیک",
        "slaughter":"🩸 سلاخی", "night":"🌙 شب", "day":"☀️ روز",
        "win":"🏆 برد", "lose":"💔 باخت", "leader":"👑 سردست", "game":"🎮 بازی", "role":"🎭 نقش",
    }
    for key, fallback in DEFAULT_EMOJIS.items():
        current = "✨" if key in mapping else fallback
        builder.row(InlineKeyboardButton(
            text=f"{current} {labels.get(key, key)}",
            callback_data=f"groupdefaults:emoji_set:{group_id}:{key}",
        ))
    builder.row(InlineKeyboardButton(text="🧹 حذف همه اموجی‌های بازی", callback_data=f"groupdefaults:emoji_clear:{group_id}"))
    _back(builder, f"groupdefaults:emoji_menu:{group_id}")
    return builder.as_markup()


def group_achievement_emoji_menu(group_id: int, achievements, back_callback: str | None = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for achievement in achievements:
        current = "✨" if getattr(achievement, "custom_emoji_id", None) else (achievement.icon or "🏅")
        builder.row(InlineKeyboardButton(
            text=f"{current} {achievement.name_fa}",
            callback_data=f"groupdefaults:achievement_emoji:{group_id}:{achievement.key}",
        ))
    builder.row(InlineKeyboardButton(text="🧹 حذف اموجی سفارشی دستاوردها", callback_data=f"groupdefaults:achievement_emoji_clear:{group_id}"))
    _back(builder, back_callback or f"groupdefaults:emoji_menu:{group_id}")
    return builder.as_markup()


def group_tag_emoji_menu(group_id: int, tags, back_callback: str | None = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for achievement in tags:
        current = "✨" if getattr(achievement, "tag_custom_emoji_id", None) else (achievement.tag_emoji or "🏷️")
        builder.row(InlineKeyboardButton(
            text=f"{current} {achievement.tag_name or achievement.name_fa}",
            callback_data=f"groupdefaults:tag_emoji:{group_id}:{achievement.key}",
        ))
    builder.row(InlineKeyboardButton(text="🧹 حذف اموجی سفارشی تگ‌ها", callback_data=f"groupdefaults:tag_emoji_clear:{group_id}"))
    _back(builder, back_callback or f"groupdefaults:emoji_menu:{group_id}")
    return builder.as_markup()


def group_voting_settings_menu(group_id: int, settings) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text=f"🗳 حالت رأی اول: {'خودکار' if settings.default_voting_mode == 'auto' else 'دستی'}",
        callback_data=f"groupdefaults:toggle_mode:{group_id}:voting",
    ))
    builder.row(InlineKeyboardButton(
        text=f"🗳 رأی دوم: {'خودکار' if settings.default_vote2_selection_mode == 'auto' else 'دستی'}",
        callback_data=f"groupdefaults:toggle_mode:{group_id}:vote2",
    ))
    builder.row(
        InlineKeyboardButton(text=f"⏳ مکث رأی: {settings.default_voting_pre_delay_seconds}s", callback_data=f"groupdefaults:vote_time:{group_id}:pre"),
        InlineKeyboardButton(text=f"⏱ زمان رأی: {settings.default_vote_seconds}s", callback_data=f"groupdefaults:vote_time:{group_id}:vote"),
    )
    _back(builder, "groupmgmt:defaults")
    return builder.as_markup()


def group_default_scenario_keyboard(group_id: int, scenarios) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for scenario in scenarios:
        builder.row(InlineKeyboardButton(
            text=f"🎭 {scenario.name_fa}",
            callback_data=f"groupdefaults:setscenario:{group_id}:{scenario.id}",
        ))
    builder.row(InlineKeyboardButton(text="🧹 بدون سناریوی پیش‌فرض", callback_data=f"groupdefaults:setscenario:{group_id}:0"))
    _back(builder, "groupmgmt:defaults")
    return builder.as_markup()


def group_player_settings_menu(group_id: int, settings) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for field, label in (
        ("allow_player_join", "پیوستن بازیکن"),
        ("allow_reserve_queue", "صف رزرو"),
        ("allow_substitute_queue", "صف جایگزین"),
        ("auto_silence_on_max_warning", "سکوت خودکار"),
        ("auto_kick_on_max_warning", "کیک خودکار"),
    ):
        builder.row(InlineKeyboardButton(
            text=f"{'✅' if getattr(settings, field) else '❌'} {label}",
            callback_data=f"groupplayers:toggle:{group_id}:{field}",
        ))
    builder.row(InlineKeyboardButton(
        text=f"⚠️ سقف تذکر: {settings.max_warnings}",
        callback_data=f"groupplayers:warnings:{group_id}",
    ))
    _back(builder, "menu:group_management")
    return builder.as_markup()


def group_notification_settings_menu(group_id: int, settings) -> InlineKeyboardMarkup:
    import json
    defaults = {
        "game_start": True, "game_end": True, "role_distribution": True,
        "player_join_leave": True, "turn": True, "challenge": True,
        "vote": True, "night": True, "reserve_substitute": True,
    }
    try:
        values = {**defaults, **json.loads(settings.notification_settings or "{}")}
    except (TypeError, ValueError):
        values = defaults
    labels = (
        ("game_start", "شروع بازی"),
        ("game_end", "پایان بازی"),
        ("role_distribution", "پخش نقش"),
        ("player_join_leave", "ورود/خروج بازیکن"),
        ("turn", "نوبت‌ها"),
        ("challenge", "چالش‌ها"),
        ("vote", "رأی‌گیری"),
        ("night", "فاز شب"),
        ("reserve_substitute", "رزرو/جایگزین"),
    )
    for key, label in labels:
        builder.row(InlineKeyboardButton(
            text=f"{'✅' if values.get(key, True) else '❌'} {label}",
            callback_data=f"groupnotify:toggle:{group_id}:{key}",
        ))
    _back(builder, "menu:group_management")
    return builder.as_markup()


def group_list_keyboard(groups, purpose: str = "games", back_callback: str = "menu:group_management") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for group in groups:
        title = group.title or f"گروه {group.telegram_id}"
        builder.row(InlineKeyboardButton(text=title[:64], callback_data=f"groupmgmt:select:{purpose}:{group.id}"))
    _back(builder, back_callback)
    return builder.as_markup()


def group_lobby_media_menu(group_id: int, settings) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    enabled = bool(getattr(settings, "lobby_media_enabled", True))
    media_type = getattr(settings, "lobby_media_type", None)
    has_custom = bool(getattr(settings, "lobby_media_file_id", None) and media_type)
    status = "فعال" if enabled else "غیرفعال"
    source = "ویدیوی سفارشی" if media_type == "video" else ("عکس سفارشی" if media_type == "photo" else "عکس پروفایل گروه")
    builder.row(InlineKeyboardButton(
        text=f"🎬 رسانه لابی: {status}",
        callback_data=f"group_lobby_media:toggle:{group_id}",
    ))
    builder.row(InlineKeyboardButton(
        text=f"📌 منبع فعلی: {source}",
        callback_data=f"group_lobby_media:noop:{group_id}",
    ))
    builder.row(InlineKeyboardButton(
        text="📤 ثبت/تغییر عکس یا ویدیو",
        callback_data=f"group_lobby_media:set:{group_id}",
    ))
    if has_custom:
        builder.row(InlineKeyboardButton(
            text="🧹 حذف رسانه سفارشی",
            callback_data=f"group_lobby_media:clear:{group_id}",
        ))
    _back(builder, "menu:group_management")
    return builder.as_markup()

def group_invitation_menu(group_id: int, has_default: bool, exception_count: int = 0) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="📤 ارسال پیام", callback_data=f"invitation:send:{group_id}"))
    builder.row(InlineKeyboardButton(text="✏️ ویرایش پیام پیش‌فرض" if has_default else "➕ ایجاد پیام پیش‌فرض", callback_data=f"invitation:edit:{group_id}"))
    builder.row(InlineKeyboardButton(text="👁 نمایش پیام پیش‌فرض", callback_data=f"invitation:show:{group_id}"))
    builder.row(InlineKeyboardButton(text=f"🚫 استثناها ({exception_count})", callback_data=f"invitation:exceptions:{group_id}"))
    _back(builder, "menu:group_management")
    return builder.as_markup()

def group_invitation_send_menu(group_id: int, has_default: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="📌 پیام پیش‌فرض", callback_data=f"invitation:preview_default:{group_id}") if has_default else InlineKeyboardButton(text="📌 پیام پیش‌فرض (ثبت نشده)", callback_data=f"invitation:missing_default:{group_id}"))
    builder.row(InlineKeyboardButton(text="✍️ ایجاد پیام", callback_data=f"invitation:create:{group_id}"))
    _back(builder, f"invitation:menu:{group_id}")
    return builder.as_markup()

def invitation_confirm_keyboard(group_id: int, mode: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="✅ تأیید و ارسال", callback_data=f"invitation:confirm:{mode}:{group_id}"), InlineKeyboardButton(text="❌ لغو", callback_data=f"invitation:menu:{group_id}"))
    return builder.as_markup()

def group_invitation_exception_menu(group_id: int, count: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=f"👥 بازیکنان مستثنی ({count})", callback_data=f"invitation:exception_list:{group_id}"))
    builder.row(InlineKeyboardButton(text="➕ ایجاد استثنا", callback_data=f"invitation:exception_add:{group_id}"))
    _back(builder, f"invitation:menu:{group_id}")
    return builder.as_markup()

def group_invitation_exception_list_menu(group_id: int, users) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for user in users:
        name = getattr(user, "display_name", None) or getattr(user, "first_name", None) or str(getattr(user, "telegram_id", ""))
        builder.row(InlineKeyboardButton(text=f"🚫 {name[:45]}", callback_data=f"invitation:exception_remove:{group_id}:{user.id}"))
    builder.row(InlineKeyboardButton(text="➕ ایجاد استثنا", callback_data=f"invitation:exception_add:{group_id}"))
    _back(builder, f"invitation:exceptions:{group_id}")
    return builder.as_markup()
def invitation_exception_remove_keyboard(group_id: int, user_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🗑 حذف از استثنا", callback_data=f"invitation:exception_remove:{group_id}:{user_id}"))
    _back(builder, f"invitation:exception_list:{group_id}")
    return builder.as_markup()

def invitation_copy_keyboard(value: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="📋 کپی متن", copy_text=CopyTextButton(text=value[:256])))
    return builder.as_markup()
def group_game_menu(group_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="تاریخچه بازی‌ها", callback_data=f"groupgame:history:{group_id}"))
    _back(builder, "menu:group_management")
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


def active_game_entry_keyboard(group_id: int) -> InlineKeyboardMarkup:
    """Single-button entry point used on the pinned public roster."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="🎮 مدیریت بازی",
            callback_data=f"groupmgmt:select:active:{group_id}",
        )
    )
    return builder.as_markup()


def _game_menu_context(back_callback: str | None) -> str:
    """Identify where the active-game menu was opened from.

    The context is intentionally tiny because it is carried inside Telegram
    callback_data. It lets shared scenario/host handlers return to the correct
    parent menu instead of always rendering the lobby.
    """
    if back_callback == "groupmgmt:games":
        return "groups"
    if back_callback and back_callback.startswith("game:return_lobby:"):
        return "lobby"
    return "main"


def active_game_menu(
    group_id: int,
    back_callback: str | None = None,
    game_key: str | None = None,
    lobby_editable: bool = False,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    context = _game_menu_context(back_callback)
    builder.row(InlineKeyboardButton(text="ℹ️ اطلاعات بازی", callback_data=f"gameadmin:info:{group_id}"))
    builder.row(InlineKeyboardButton(text="🛑 لغو بازی", callback_data=f"gameadmin:feature:{group_id}:cancel"))
    builder.row(InlineKeyboardButton(text="🏁 پایان بازی", callback_data=f"gameadmin:feature:{group_id}:finish"))
    builder.row(InlineKeyboardButton(text="📜 اتفاقات بازی", callback_data=f"gameadmin:feature:{group_id}:events"))
    builder.row(InlineKeyboardButton(text="🔢 تعیین شماره بازی", callback_data=f"gameadmin:number:{group_id}"))
    builder.row(InlineKeyboardButton(text="👥 مدیریت بازیکنان", callback_data=f"gameadmin:players:{group_id}"))
    builder.row(InlineKeyboardButton(text="⚙️ تنظیمات بازی", callback_data=f"gameadmin:features:{group_id}"))
    builder.row(InlineKeyboardButton(text="✨ امکانات اضافی", callback_data=f"gameadmin:extras:{group_id}"))
    if lobby_editable and game_key:
        builder.row(
            InlineKeyboardButton(text="🎭 تغییر سناریو", callback_data=f"gameadmin:scenario:{game_key}:{context}"),
            InlineKeyboardButton(text="🎙 تغییر گرداننده", callback_data=f"gameadmin:host:{game_key}:{context}"),
        )
    _back(builder, back_callback or "menu:active_game")
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


def player_target_management_keyboard(group_id: int, action: str, players, *, only_alive: bool = False, only_dead: bool = False, only_reserve: bool = False, only_substitute: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for player, user in players:
        if only_alive and (player.is_reserved or not player.alive):
            continue
        if only_dead and (player.is_reserved or player.alive or player.exit_type != "death"):
            continue
        if only_reserve and (not player.is_reserved or getattr(player, "is_substitute", False)):
            continue
        if only_substitute and not getattr(player, "is_substitute", False):
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


def player_replace_destination_keyboard(group_id: int, source_id: int, players) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for player, user in players:
        if player.is_reserved or not player.alive:
            continue
        name = user.display_name or user.first_name or user.username or str(user.telegram_id)
        builder.row(InlineKeyboardButton(
            text=f"{player.seat}. {name[:38]}",
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
    game_key: str | None = None,
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
    builder.row(InlineKeyboardButton(text="🛑 لغو بازی", callback_data=f"gameadmin:feature:{group_id}:cancel"))
    builder.row(InlineKeyboardButton(text="📜 ثبت اتفاقات بازی", callback_data=f"gameadmin:feature:{group_id}:events"))
    builder.row(InlineKeyboardButton(text="مدیریت اموجی‌ها", callback_data=f"gameadmin:emoji:{group_id}"))
    if game_key:
        builder.row(
            InlineKeyboardButton(text="🎭 تغییر سناریو", callback_data=f"gameadmin:scenario:{game_key}"),
            InlineKeyboardButton(text="🎙 تغییر گرداننده", callback_data=f"gameadmin:host:{game_key}"),
        )
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


def game_extras_menu(group_id: int, auto_play: bool = False, turn_color: str = "پیش‌فرض", challenge_color: str = "پیش‌فرض", turn_color_enabled: bool = True, custom_emoji: bool = False, back_callback: str | None = None) -> InlineKeyboardMarkup:
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
    builder.row(InlineKeyboardButton(
        text=f"✨ اموجی سفارشی: {'فعال' if custom_emoji else 'غیرفعال'}",
        callback_data=f"gameadmin:extra:{group_id}:custom_emoji",
    ))
    _back(builder, back_callback or f"gameadmin:active:{group_id}")
    return builder.as_markup()


def game_event_game_selector(games) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for game, scenario, group in games:
        label = f"#{game.id} | {group.title[:20]} | {scenario.name_fa[:24]}"
        builder.row(InlineKeyboardButton(text=label, callback_data=f"gameadmin:event_game:{game.id}"))
    _back(builder, "menu:root")
    return builder.as_markup()


def game_event_management_keyboard(game_id: int, group_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="➕ ثبت اتفاق جدید", callback_data=f"gameadmin:event_add:{game_id}"))
    _back(builder, f"gameadmin:features:{group_id}")
    return builder.as_markup()


def cancel_game_keyboard(group_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="تأیید لغو بازی", callback_data=f"gameadmin:cancel_confirm:{group_id}"),
        InlineKeyboardButton(text="انصراف", callback_data=f"gameadmin:features:{group_id}"),
    )
    return builder.as_markup()


def finish_game_keyboard(group_id: int, back_callback: str | None = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for key, label in (
        ("citizen", "برد شهروند"),
        ("mafia", "برد مافیا"),
        ("independent", "برد مستقل"),
        ("citizen_independent", "برد شهروند/مستقل"),
        ("draw", "مساوی"),
    ):
        builder.row(InlineKeyboardButton(text=label, callback_data=f"gameadmin:finish_result:{group_id}:{key}"))
    _back(builder, back_callback or f"gameadmin:features:{group_id}")
    return builder.as_markup()


def finish_game_confirm_keyboard(group_id: int, winner: str, back_callback: str | None = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="تأیید نتیجه", callback_data=f"gameadmin:finish_confirm:{group_id}:{winner}"))
    builder.row(InlineKeyboardButton(text="تغییر برنده", callback_data=f"gameadmin:finish_change:{group_id}"))
    _back(builder, back_callback or f"gameadmin:features:{group_id}")
    return builder.as_markup()


def game_result_keyboard(group_id: int, game_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🏁 نتیجه بازی", callback_data=f"gameresult:view:result:{game_id}"),
        InlineKeyboardButton(text="🎭 نقش‌ها", callback_data=f"gameresult:view:roles:{game_id}"),
        InlineKeyboardButton(text="🏆 رتبه‌بندی", callback_data=f"gameresult:view:ranking:{game_id}"),
    )
    builder.row(
        InlineKeyboardButton(text="📩 نمایش نتیجه برای من", callback_data=f"gameresult:private:{game_id}"),
    )
    return builder.as_markup()

def game_result_back_keyboard(game_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔙 بازگشت به نتیجه بازی", callback_data=f"gameresult:back:{game_id}"))
    return builder.as_markup()


def bot_settings_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="⚙️ تنظیمات عمومی", callback_data="botsettings:general"))
    builder.row(InlineKeyboardButton(text="🔔 تنظیمات اعلان ها", callback_data="botsettings:notifications"))
    _back(builder)
    return builder.as_markup()

def general_bot_settings_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="👤 پروفایل و نام نمایشی", callback_data="menu:profile"))
    builder.row(InlineKeyboardButton(text="🏷️ تگ فعال", callback_data="profile:tags"))
    builder.row(InlineKeyboardButton(text="🔔 تنظیمات اعلان‌ها", callback_data="botsettings:notifications"))
    _back(builder, "menu:bot_settings")
    return builder.as_markup()

def notification_settings_menu(user) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    items = (
        ("notify_game_result", "نتیجه بازی"),
        ("notify_achievements", "دستاوردهای جدید"),
        ("notify_rank_changes", "تغییر رتبه"),
        ("notify_challenges", "درخواست‌های چالش"),
        ("notify_turns", "نوبت‌های بازی"),
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
    builder.row(InlineKeyboardButton(text="🎂 تاریخ تولد", callback_data="profile:birthday"))
    builder.row(InlineKeyboardButton(text="📥 دریافت از پروفایل تلگرام", callback_data="profile:birthday_import"))
    builder.row(InlineKeyboardButton(text="🏅 دستاوردها", callback_data="menu:achievements"))
    _back(builder)
    return builder.as_markup()

def profile_tags_keyboard(tags, active_key: str | None = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for achievement in tags:
        mark = "✅" if achievement.tag_key == active_key else "🏷️"
        current = "✨" if getattr(achievement, "tag_custom_emoji_id", None) else (achievement.tag_emoji or "🏷️")
        label = f"{mark} {current} {achievement.tag_name or achievement.name_fa}"
        builder.row(InlineKeyboardButton(text=label, callback_data=f"profile:tag:{achievement.tag_key}"))
    if active_key:
        builder.row(InlineKeyboardButton(text="🧹 حذف تگ فعال", callback_data="profile:tag:clear"))
    if not tags:
        builder.row(InlineKeyboardButton(text="🏅 مشاهده دستاوردها", callback_data="profile:achievements"))
    _back(builder)
    return builder.as_markup()

def scenario_management_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="➕ ایجاد سناریو", callback_data="scenario_admin:create"))
    builder.row(InlineKeyboardButton(text="✏️ ویرایش سناریو", callback_data="scenario_admin:edit"))
    builder.row(InlineKeyboardButton(text="🗑 حذف سناریو", callback_data="scenario_admin:delete"))
    builder.row(InlineKeyboardButton(text="🎭 نقش‌ها و توضیحات", callback_data="scenario_admin:roles"))
    _back(builder)
    return builder.as_markup()

def scenario_admin_list_keyboard(scenarios, action: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for scenario in scenarios:
        state = "فعال" if scenario.enabled else "غیرفعال"
        builder.button(
            text=f"🎭 {scenario.name_fa} — {state}",
            callback_data=f"scenario_admin:{action}:{scenario.id}",
        )
    if scenarios:
        builder.adjust(3)
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


def scenario_keyboard(scenarios=()) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for scenario in scenarios:
        builder.button(text=f"🎭 {scenario.name_fa}", callback_data=f"scenario:{scenario.id}")
    if scenarios: builder.adjust(3)
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
    """Round setup menu: leader, challenge/next status, management and start."""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="👑 انتخاب سردست", callback_data=f"leader:menu:{game_key}"))
    builder.row(
        InlineKeyboardButton(
            text=f"🤏🏻 چالش: {'فعال' if game.challenge_enabled else 'غیرفعال'}",
            callback_data=f"round:toggle_challenge:{game_key}",
        ),
        InlineKeyboardButton(
            text="⏩ تنظیم نکست",
            callback_data=f"round:next_menu:{game_key}",
        ),
    )
    if leader_selected:
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

def continue_night_keyboard(game_key: str, night_locked: bool = False, chat_locked: bool = False, turn_locked: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
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
    builder.row(InlineKeyboardButton(
        text=f"قفل نوبت: {'فعال' if turn_locked else 'غیرفعال'}",
        callback_data=f"night:lock:{game_key}:turn_lock",
    ))
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
    builder.row(InlineKeyboardButton(text="🗳 رای میدم", callback_data=f"vote1:cast:{game_key}:{target_user_id}"))
    builder.row(InlineKeyboardButton(text="⏩ نفر بعدی", callback_data=f"vote1:next:{game_key}"))
    return builder.as_markup()


def vote1_complete_keyboard(game_key: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🗳 شروع رای ۲", callback_data=f"vote2:start:{game_key}"))
    builder.row(InlineKeyboardButton(text="🌙 شروع فاز شب", callback_data=f"day:night:{game_key}"))
    builder.row(InlineKeyboardButton(text="🏁 اتمام بازی", callback_data=f"day:finish:{game_key}"))
    return builder.as_markup()


def defense_selection_keyboard(game_key: str, players, selected_ids: set[int] | None = None, vote_counts: dict[int, int] | None = None) -> InlineKeyboardMarkup:
    selected_ids = selected_ids or set()
    vote_counts = vote_counts or {}
    builder = InlineKeyboardBuilder()
    for player, user, *_ in players:
        if player.alive:
            name = tg_plain_name(user.display_name or user.first_name or user.username or str(user.telegram_id))
            mark = "✅" if user.id in selected_ids else "⬜"
            count = int(vote_counts.get(int(user.id), 0))
            builder.row(InlineKeyboardButton(text=f"{mark} {name} — {count} رای", callback_data=f"vote2:select:{game_key}:{user.id}"))
    builder.row(InlineKeyboardButton(text="🗳 شروع رای ۲", callback_data=f"vote2:begin:{game_key}"))
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
    builder.row(InlineKeyboardButton(text="🏁 پایان بازی", callback_data=f"day:finish:{game_key}"))
    return builder.as_markup()

def vote2_setup_keyboard(game_key: str, selection_mode: str = "manual") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text=f"نوع رای گیری دوم: {'خودکار' if selection_mode == 'auto' else 'دستی'}",
        callback_data=f"vote2:mode:{game_key}",
    ))
    builder.row(InlineKeyboardButton(
        text="🛡️ انتخاب بازیکنان برای دفاع",
        callback_data=f"vote2:choose:{game_key}",
    ))
    builder.row(InlineKeyboardButton(text="🗳 شروع رای ۲", callback_data=f"vote2:begin:{game_key}"))
    return builder.as_markup()


def vote2_target_keyboard(game_key: str, target_user_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🗳 رای میدم", callback_data=f"vote2:cast:{game_key}:{target_user_id}"))
    return builder.as_markup()

def vote2_private_voters_keyboard(game_key: str, voters, voted_ids: set[int] | None = None) -> InlineKeyboardMarkup:
    voted_ids = voted_ids or set()
    builder = InlineKeyboardBuilder()
    for user_id, name in voters:
        mark = "✅" if int(user_id) in voted_ids else "🗳"
        builder.row(InlineKeyboardButton(
            text=f"{mark} {name}",
            callback_data=f"vote2:private:voter:{game_key}:{int(user_id)}",
        ))
    return builder.as_markup()


def vote2_private_targets_keyboard(game_key: str, voter_id: int, candidates) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for user_id, name in candidates:
        builder.row(InlineKeyboardButton(
            text=name,
            callback_data=f"vote2:private:cast:{game_key}:{int(voter_id)}:{int(user_id)}",
        ))
    builder.row(InlineKeyboardButton(text="بازگشت", callback_data=f"vote2:private:panel:{game_key}"))
    return builder.as_markup()

def vote2_ballot_keyboard(game_key: str, candidates, selected_user_id: int | None = None, host_only: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for user_id, name in candidates:
        mark = "🔘" if selected_user_id is not None and int(user_id) == int(selected_user_id) else "⚪"
        builder.row(InlineKeyboardButton(
            text=f"{mark} {name}",
            callback_data=f"vote2:cast:{game_key}:{int(user_id)}",
        ))
    builder.row(InlineKeyboardButton(
        text="اتمام رای گیری",
        callback_data=f"vote2:finish:{game_key}",
    ))
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


def readiness_keyboard(game_key: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="✅ آماده‌ام",
            callback_data=f"ready:toggle:{game_key}",
        )
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
    builder.row(InlineKeyboardButton(text="⚙️ تنظیمات بازی", callback_data=f"newgame:settings:{group_id}"))
    builder.row(InlineKeyboardButton(text="امکانات اضافه", callback_data=f"newgame:extras:{group_id}"))
    builder.row(InlineKeyboardButton(text="ایجاد بازی", callback_data=f"newgame:create:{group_id}"))
    builder.row(InlineKeyboardButton(text="بازگشت", callback_data=f"groupstart:root:{group_id}"))
    return builder.as_markup()


def scenario_select_keyboard(group_id: int, scenarios, back_callback: str | None = None, callback_prefix: str = "newgame:setscenario") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for scenario in scenarios:
        builder.button(text=f"🎭 {scenario.name_fa}", callback_data=f"{callback_prefix}:{group_id}:{scenario.id}")
    if scenarios: builder.adjust(3)
    builder.row(InlineKeyboardButton(text="بازگشت", callback_data=back_callback or f"newgame:menu:{group_id}"))
    return builder.as_markup()


def host_select_keyboard(group_id: int, admins, callback_prefix: str = "newgame:sethost", back_callback: str | None = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for member in admins:
        user = member.user
        name = user.full_name or user.username or str(user.id)
        builder.row(InlineKeyboardButton(text=tg_plain_name(name[:60]), callback_data=f"{callback_prefix}:{group_id}:{user.id}"))
    builder.row(InlineKeyboardButton(text="بازگشت", callback_data=back_callback or f"newgame:menu:{group_id}"))
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

def lobby_keyboard_v2(game_key: str, scenario, players, reserves, substitutes=None, is_host: bool = False, can_deal: bool = False, reserve_enabled: bool = True, training_url: str | None = None, telegram_training_url: str | None = None) -> InlineKeyboardMarkup:
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
        builder.row(InlineKeyboardButton(text="🪑 رزرو", callback_data=f"lobby:reserve:{game_key}"))
    builder.row(InlineKeyboardButton(text="🔁 ثبت جایگزین", callback_data=f"lobby:substitute:{game_key}"))
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
            InlineKeyboardButton(text="👥 مدیریت گروه", callback_data=f"groupadmin:lobby:{game_key}"),
        )
    return builder.as_markup()


def admin_panel_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="📊 داشبورد", callback_data="admin:dashboard"))
    builder.row(InlineKeyboardButton(text="👥 گروه‌ها", callback_data="admin:groups"))
    builder.row(InlineKeyboardButton(text="🎭 سناریوها", callback_data="admin:scenarios"))
    builder.row(InlineKeyboardButton(text="🎮 بازی‌های اخیر", callback_data="admin:games"))
    builder.row(InlineKeyboardButton(text="🎂 مدیریت تبریک تولد", callback_data="admin:birthday"))
    builder.row(InlineKeyboardButton(text="⚙️ تنظیمات ربات", callback_data="admin:settings"))
    _back(builder, "menu:root")
    return builder.as_markup()


def birthday_admin_menu(video_file_id: str | None, message_count: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text=f"🎬 ویدیوی تبریک: {'تنظیم شده' if video_file_id else 'تنظیم نشده'}",
        callback_data="admin:birthday:video",
    ))
    builder.row(InlineKeyboardButton(
        text=f"💬 پیام‌های تبریک ({message_count})",
        callback_data="admin:birthday:messages",
    ))
    builder.row(InlineKeyboardButton(text="➕ افزودن پیام تبریک", callback_data="admin:birthday:add"))
    _back(builder, "menu:admin")
    return builder.as_markup()


def birthday_message_list_keyboard(messages) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for item in messages:
        preview = (item.text or "").replace("\n", " ")[:48]
        builder.row(InlineKeyboardButton(
            text=f"💬 {item.id}: {preview}",
            callback_data=f"admin:birthday:show:{item.id}",
        ))
    builder.row(InlineKeyboardButton(text="➕ افزودن پیام", callback_data="admin:birthday:add"))
    _back(builder, "admin:birthday")
    return builder.as_markup()


def birthday_message_item_keyboard(message_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🗑 حذف پیام", callback_data=f"admin:birthday:delete:{message_id}"))
    _back(builder, "admin:birthday:messages")
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


def tournament_admin_menu(group_id: int) -> InlineKeyboardMarkup:
    b=InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="➕ افزودن تورنمنت", callback_data=f"tournament:add:{group_id}"))
    b.row(InlineKeyboardButton(text="🗂 مدیریت تورنمنت‌ها", callback_data=f"tournament:list:{group_id}"))
    _back(b, "menu:group_management")
    return b.as_markup()

def tournament_manage_menu(tid: int, group_id: int) -> InlineKeyboardMarkup:
    b=InlineKeyboardBuilder()
    for label, action in (
        ("✏️ ویرایش تورنمنت","edit"),("🗑 حذف تورنمنت","delete"),
        ("👤 افزودن بازیکن","add_player"),("🏅 ثبت امتیاز","score"),
        ("🏁 ثبت گروه فینال","final"),("🎲 قرعه‌کشی","draw"),
        ("👥 مدیریت گروه‌ها","groups"),("🏆 پایان تورنمنت","finish"),
    ):
        b.row(InlineKeyboardButton(text=label, callback_data=f"tournament:{action}:{tid}"))
    _back(b, f"tournament:list:{group_id}")
    return b.as_markup()

def tournament_public_menu(tid: int) -> InlineKeyboardMarkup:
    b=InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🏆 جدول امتیازات", callback_data=f"tourpub:scores:{tid}"))
    b.row(InlineKeyboardButton(text="👥 گروه‌بندی", callback_data=f"tourpub:groups:{tid}"))
    b.row(InlineKeyboardButton(text="🎮 بازی‌ها", callback_data=f"tourpub:games:{tid}"))
    _back(b, "menu:tournaments")
    return b.as_markup()


def round_next_menu_keyboard(game_key: str, game) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text=f"👑 نکست گرداننده {'✅' if game.next_host_enabled else '❌'}", callback_data=f"round:toggle_next_host:{game_key}"))
    b.row(InlineKeyboardButton(text=f"👤 نکست بازیکن {'✅' if game.next_player_enabled else '❌'}", callback_data=f"round:toggle_next_player:{game_key}"))
    b.row(InlineKeyboardButton(text=f"🤖 نکست خودکار {'✅' if game.next_auto_enabled else '❌'}", callback_data=f"round:toggle_next_auto:{game_key}"))
    b.row(InlineKeyboardButton(text="🔙 بازگشت", callback_data=f"round:back:{game_key}"))
    return b.as_markup()


def scenario_confirm_keyboard(action: str = "create") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ تأیید و ذخیره", callback_data=f"scenario_admin:{action}:confirm"),
        InlineKeyboardButton(text="✏️ اصلاح اطلاعات", callback_data=f"scenario_admin:{action}:back"),
    )
    builder.row(InlineKeyboardButton(text="❌ لغو", callback_data="scenario_admin:cancel"))
    return builder.as_markup()


def scenario_role_description_list_keyboard(roles, scenario_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for role in roles:
        builder.row(
            InlineKeyboardButton(
                text=f"🎭 {role.name_fa[:35]}",
                callback_data=f"scenario_admin:role_desc:{scenario_id}:{role.id}",
            )
        )
    builder.row(InlineKeyboardButton(text="↩️ بازگشت", callback_data="scenario_admin:cancel"))
    return builder.as_markup()
