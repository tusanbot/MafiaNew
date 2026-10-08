from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup, ForceReply
from aiogram.utils.keyboard import InlineKeyboardBuilder
from html import escape
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from sqlalchemy import desc, func, select
import json
import re

from app.db.models import Game, GameEvent, GamePlayer, GameResultViewer, Group, GroupSettings, GroupInvitationSetting, GroupInvitationException, Role, Scenario, ScenarioRole, User, Vote, Achievement, Tournament, TournamentPlayer, TournamentGroup, BirthdayMessageTemplate, BirthdaySetting
from app.db.session import session_factory
from app.handlers.keyboards import (
    active_game_menu,
    bot_settings_menu,
    game_extras_menu,
    game_features_menu,
    group_game_menu,
    group_list_keyboard,
    group_lock_keyboard,
    group_management_menu,
    group_default_settings_menu,
    group_player_settings_menu,
    group_notification_settings_menu,
    group_visual_settings_menu,
    group_custom_emoji_menu,
    group_game_emoji_menu,
    group_achievement_emoji_menu,
    group_tag_emoji_menu,
    group_lobby_media_menu,
    group_invitation_menu,
    group_invitation_send_menu,
    invitation_confirm_keyboard,
    invitation_button_choice_keyboard,
    group_invitation_exception_menu,
    group_invitation_exception_list_menu,
    invitation_copy_keyboard,
    group_voting_settings_menu,
    group_default_scenario_keyboard,
    group_scenario_management_menu,
    main_menu,
    player_management_menu,
    player_target_management_keyboard,
    player_replace_destination_keyboard,
    player_faceoff_destination_keyboard,
    ranking_menu,
    admin_panel_menu,
    admin_scenario_keyboard,
    scenario_management_menu,
    scenario_admin_list_keyboard,
    scenario_role_keyboard,
    scenario_challenge_keyboard,
    scenario_delete_confirm_keyboard,
    scenario_confirm_keyboard,
    scenario_role_description_list_keyboard,
    notification_settings_menu,
    general_bot_settings_menu,
    finish_game_confirm_keyboard,
    game_result_keyboard,
    game_result_back_keyboard,
    scenario_select_keyboard,
    host_select_keyboard,
    game_event_management_keyboard,
    game_event_game_selector,
    tournament_admin_menu,
    tournament_manage_menu,
    tournament_public_menu,
    birthday_user_customization_keyboard,
    group_birthday_menu,
    group_birthday_list_keyboard,
)
from app.repositories.games import GameRepository
from app.repositories.users import UserRepository
from app.services.game import create_game, get_game_number, set_game_number, release_game_number
from app.services.profile import sync_telegram_user
from app.services.birthday import parse_birthday, birthday_label, get_telegram_profile_birthday
from app.services.gameplay import current_round, _event
from app.services.player_management import (
    remove_player,
    restore_removed_player,
    apply_kick,
    swap_roles_for_faceoff,
    silence_target_round,
    grant_extra_turn,
    parse_turn_payload,
)
from app.services.stats import leaderboard, rank_for_score
from app.services.rich_message import edit_rich_message, send_rich_message
from app.config import get_settings
from app.utils.text import tg_name, tg_mention
from app.utils.custom_emoji import dump_emoji_map, extract_custom_emoji_id, game_emoji, normalize_emoji_map, custom_emoji_html
from uuid import uuid4

router = Router(name="menu")
STATUS_LABELS = {"draft": "پیش‌نویس", "waiting": "در انتظار شروع", "running": "در حال اجرا", "finished": "پایان‌یافته", "cancelled": "لغوشده"}
PHASE_LABELS = {"lobby": "لابی", "setup": "آماده‌سازی", "day": "روز", "night": "شب", "vote_setup": "تنظیم رأی", "voting1": "رأی اول", "vote1_complete": "پایان رأی اول", "defense": "دفاع", "voting2": "رأی دوم", "vote2_complete": "پایان رأی دوم", "result": "نتیجه", "finished": "پایان‌یافته"}
def _status_fa(value: str | None) -> str:
    return STATUS_LABELS.get(str(value or ""), str(value or "نامشخص"))
def _phase_fa(value: str | None) -> str:
    return PHASE_LABELS.get(str(value or ""), str(value or "نامشخص"))


class GameEventState(StatesGroup):
    description = State()
    game_number = State()


class CustomEmojiState(StatesGroup):
    emoji = State()

class TournamentState(StatesGroup):
    input = State()


class GroupBirthdayState(StatesGroup):
    input = State()
    message = State()
    media = State()

class GroupBirthdayDefaultState(StatesGroup):
    message = State()
    media = State()


class GroupLobbyMediaState(StatesGroup):
    media = State()


class GroupInvitationState(StatesGroup):
    message = State()
    exception = State()


class BirthdayAdminState(StatesGroup):
    video = State()
    message = State()


class ScenarioAdminState(StatesGroup):
    name = State()
    description = State()
    min_players = State()
    max_players = State()
    turn_time = State()
    challenge_time = State()
    extra_challenge_time = State()
    challenge = State()
    vote_threshold = State()
    vote_rules = State()
    roles = State()
    confirm = State()


class RoleDescriptionState(StatesGroup):
    input = State()
    sequence = State()


class ScenarioTrainingState(StatesGroup):
    input = State()


async def _is_group_admin(bot, group: Group, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(group.telegram_id, user_id)
        return member.status in ("creator", "administrator")
    except Exception:
        return False


async def _bot_is_active(bot, group: Group) -> bool:
    try:
        me = await bot.get_me()
        member = await bot.get_chat_member(group.telegram_id, me.id)
        return member.status not in ("left", "kicked")
    except Exception:
        return False


async def _manageable_groups(session, bot, user_id: int) -> list[Group]:
    result = await session.execute(
        select(Group).where(Group.is_active.is_(True)).order_by(Group.title)
    )
    groups = []
    for group in result.scalars().all():
        if await _is_group_admin(bot, group, user_id) and await _bot_is_active(bot, group):
            groups.append(group)
    return groups


async def _game_player(session, game_id: int, telegram_user_id: int):
    user = await session.scalar(select(User).where(User.telegram_id == telegram_user_id))
    if not user:
        return None
    return await session.scalar(select(GamePlayer).where(
        GamePlayer.game_id == game_id,
        GamePlayer.user_id == user.id,
    ))


async def _is_game_participant(session, game_id: int, telegram_user_id: int) -> bool:
    return (await _game_player(session, game_id, telegram_user_id)) is not None


async def _is_finished_game_player(session, game_id: int, telegram_user_id: int) -> bool:
    user = await session.scalar(select(User).where(User.telegram_id == telegram_user_id))
    if not user:
        return False
    player = await session.scalar(select(GamePlayer).where(
        GamePlayer.game_id == game_id,
        GamePlayer.user_id == user.id,
        GamePlayer.is_reserved.is_(False),
        GamePlayer.role_id.is_not(None),
    ))
    return player is not None


async def _can_manage_game_events(session, bot, game: Game, actor: User, group: Group) -> bool:
    if not game or game.status != "running" or not actor or not group:
        return False
    is_moderator = game.host_user_id == actor.id or await _is_group_admin(bot, group, actor.telegram_id)
    if not is_moderator:
        return False
    return not await _is_game_participant(session, game.id, actor.telegram_id)


async def _selected_group(session, bot, user_id: int, group_id: int) -> Group | None:
    group = await session.get(Group, group_id)
    if not group or not group.is_active:
        return None
    if not await _is_group_admin(bot, group, user_id):
        return None
    if not await _bot_is_active(bot, group):
        return None
    return group


def _jalali_date(dt: datetime) -> str:
    """Convert Gregorian datetime to Jalali date without an external dependency."""
    gy, gm, gd = dt.year - 1600, dt.month - 1, dt.day - 1
    g_days_in_month = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
    g_day_no = 365 * gy + (gy + 3) // 4 - (gy + 99) // 100 + (gy + 399) // 400
    for month in range(gm):
        g_day_no += g_days_in_month[month]
    if gm > 1 and ((dt.year % 4 == 0 and dt.year % 100 != 0) or dt.year % 400 == 0):
        g_day_no += 1
    g_day_no += gd
    j_day_no = g_day_no - 79
    jy = 979 + 33 * (j_day_no // 12053)
    j_day_no %= 12053
    jy += 4 * (j_day_no // 1461)
    j_day_no %= 1461
    if j_day_no > 365:
        jy += (j_day_no - 1) // 365
        j_day_no = (j_day_no - 1) % 365
    if j_day_no < 186:
        jm = 1 + j_day_no // 31
        jd = 1 + j_day_no % 31
    else:
        jm = 7 + (j_day_no - 186) // 30
        jd = 1 + (j_day_no - 186) % 30
    return f"{jy:04d}/{jm:02d}/{jd:02d}"

def _tehran_datetime(value: datetime | None) -> datetime | None:
    if not value:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(ZoneInfo("Asia/Tehran"))


async def _game_result_text(session, game, winner: str) -> str:
    scenario = await session.get(Scenario, game.scenario_id)
    host = await session.get(User, game.host_user_id) if game.host_user_id else None
    rows = list((await session.execute(
        select(GamePlayer, User, Role)
        .outerjoin(Role, Role.id == GamePlayer.role_id)
        .join(User, User.id == GamePlayer.user_id)
        .where(GamePlayer.game_id == game.id)
        .order_by(GamePlayer.seat)
    )).all())

    challenge_ids: set[int] = set()
    challenge_events = await session.execute(select(GameEvent).where(
        GameEvent.game_id == game.id, GameEvent.event_type == "challenge_request"
    ))
    for event in challenge_events.scalars():
        data = json.loads(event.payload or "{}")
        if data.get("status") == "accepted" and data.get("requester_id") is not None:
            try:
                challenge_ids.add(int(data["requester_id"]))
            except (TypeError, ValueError):
                pass

    try:
        emoji_settings = json.loads(game.emoji_settings or "{}")
    except (TypeError, ValueError):
        emoji_settings = {}

    when = _tehran_datetime(game.finished_at or game.created_at) or datetime.now(ZoneInfo("Asia/Tehran"))
    winner_labels = {
        "citizen": "شهروند",
        "mafia": "مافیا",
        "independent": "مستقل",
        "citizen_independent": "شهروند / مستقل",
        "draw": "مساوی",
    }
    lines = [
        "༄",
        f"{game_emoji(game, 'game')} <b>بازی شماره : {await get_game_number(session, game)}</b>",
        f"⏱️ زمان : {when:%H:%M}",
        f"📆 تاریخ : {_jalali_date(when)}",
        f"🗓 سناریو : {escape(scenario.name_fa if scenario else 'نامشخص')}",
        f"{game_emoji(game, 'leader')} گرداننده : {tg_mention(host.telegram_id, host.display_name or host.first_name or 'گرداننده') if host else 'نامشخص'}",
        "",
        "~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~",
        "<b>لیست بازیکنان</b>",
        "",
    ]
    for index, (player, user, role) in enumerate(rows, 1):
        if player.is_reserved:
            continue
        name = tg_mention(user.telegram_id, user.display_name or user.first_name or user.username or "بازیکن")
        badges = []
        team = role.team if role else None
        if ((winner == "mafia" and team == "mafia") or
            (winner == "citizen" and team == "citizen") or
            (winner == "independent" and team == "independent") or
            (winner == "citizen_independent" and team in {"citizen", "independent"})):
            badges.append(game_emoji(game, "win"))
        if not player.alive:
            badges.append(game_emoji(game, "death"))
            if player.exit_type == "kick" and emoji_settings.get("kick", True):
                badges.append(game_emoji(game, "kick"))
            elif player.exit_type == "slaughter" and emoji_settings.get("slaughter", True):
                badges.append(game_emoji(game, "slaughter"))
            elif player.exit_type == "vote":
                badges.append(game_emoji(game, "vote"))
            elif player.exit_type == "faceoff":
                badges.append("🎭")
        if player.warning_count and emoji_settings.get("warning", True):
            badges.append(f"⚠️{player.warning_count}")


        role_name = escape(role.name_fa if role else "بدون نقش")
        badge_text = "".join(dict.fromkeys(badges))
        lines.append(f"{index}. {name}    {role_name}{(' ' + badge_text) if badge_text else ''}")

    lines.extend([
        "",
        "~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~",
        f"🏆<b>برنده: {escape(winner_labels.get(winner, winner))}</b>",
        "༄",
    ])
    return "\n".join(lines)


def _emoji_settings(game) -> dict:
    defaults = {"death": True, "kick": True, "slaughter": True, "challenge": True, "silence": True, "extra_turn": True, "warning": True}
    try:
        value = json.loads(game.emoji_settings or "{}")
        defaults.update({k: bool(v) for k, v in value.items() if k in defaults})
    except (TypeError, ValueError):
        pass
    return defaults


def _player_label(player, user, emojis: dict) -> str:
    name = user.display_name or user.first_name or user.username or str(user.telegram_id)
    marks = []
    if not player.is_reserved:
        if not player.alive and player.exit_type == "death" and emojis.get("death", True):
            marks.append("💀")
        elif not player.alive and player.exit_type == "kick" and emojis.get("kick", True):
            marks.append("⛔")
        elif not player.alive and player.exit_type == "slaughter" and emojis.get("slaughter", True):
            marks.append("🩸")
        if player.alive and player.silence_until_round is not None and emojis.get("silence", True):
            marks.append("🔇")
        if player.alive and player.extra_turn_round is not None and emojis.get("extra_turn", True):
            marks.append("➕")
        if player.warning_count and emojis.get("warning", True):
            marks.append(f"⚠️{player.warning_count}")
    return f"{' '.join(marks)} {name}".strip()


async def _public_status_roster(session, game) -> str:
    rows = await __import__("app.services.gameplay", fromlist=["all_players"]).all_players(session, game.id)
    emojis = _emoji_settings(game)
    lines = ["👥 لیست بازیکنان حاضر در بازی", ""]
    for player, user, _role in rows:
        name = tg_name(user.display_name or user.first_name or user.username or "بازیکن")
        if player.is_reserved:
            continue
        marks = []
        if player.alive:
            if player.silence_until_round is not None and emojis.get("silence", True):
                marks.append("🔇")
            if player.extra_turn_round is not None and emojis.get("extra_turn", True):
                marks.append("➕")
            if player.warning_count and emojis.get("warning", True):
                marks.append(f"⚠️{player.warning_count}")
            state = "زنده"
        else:
            if player.exit_type == "death" and emojis.get("death", True):
                marks.append("💀")
            elif player.exit_type == "kick" and emojis.get("kick", True):
                marks.append("⛔")
            elif player.exit_type == "slaughter" and emojis.get("slaughter", True):
                marks.append("🩸")
            # Face-off is deliberately never exposed in the public roster.
            state = "حذف‌شده"
        marker = " ".join(marks)
        lines.append(f"{player.seat:02d}. {marker} {name} — {state}".strip())
    return "\n".join(lines)


@router.callback_query(lambda c: c.data == "menu:admin")
async def menu_admin(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    if callback.message.chat.type != "private" or callback.from_user.id not in get_settings().admin_id_set:
        await callback.answer("دسترسی پنل مدیریت مجاز نیست.", show_alert=True)
        return
    await callback.message.edit_text("🛠 پنل مدیریت ربات\n\nبخش موردنظر را انتخاب کنید.", reply_markup=admin_panel_menu())
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("admin:"))
async def admin_panel_handler(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.message or not callback.from_user:
        return
    if callback.message.chat.type != "private" or callback.from_user.id not in get_settings().admin_id_set:
        await callback.answer("دسترسی پنل مدیریت مجاز نیست.", show_alert=True)
        return
    action = callback.data.split(":", 1)[1]
    if action == "birthday" or action.startswith("birthday:"):
        async with session_factory() as session:
            setting = await session.scalar(select(BirthdaySetting).where(BirthdaySetting.id == 1))
            messages = list((await session.execute(
                select(BirthdayMessageTemplate).order_by(BirthdayMessageTemplate.id)
            )).scalars().all())
            if action == "birthday":
                await callback.message.edit_text(
                    "🎂 مدیریت تبریک تولد\n\n"
                    "هر روز ساعت ۹ صبح به وقت تهران، برای بازیکنان متولد همان روز تبریک ارسال می‌شود.\n"
                    "ویدیو و متن‌ها از این بخش مدیریت می‌شوند.",
                    reply_markup=birthday_admin_menu(setting.video_file_id if setting else None, len(messages)),
                )
            elif action == "birthday:video":
                await state.set_state(BirthdayAdminState.video)
                await callback.message.edit_text(
                    "🎬 ویدیوی تبریک تولد را همینجا ارسال کن.\n\n"
                    "ویدیوی جدید جایگزین ویدیوی قبلی می‌شود.\n"
                    "برای لغو: /cancel"
                )
            elif action == "birthday:messages":
                await callback.message.edit_text(
                    "💬 پیام‌های تبریک ثبت‌شده:",
                    reply_markup=birthday_message_list_keyboard(messages),
                )
            elif action == "birthday:add":
                await state.set_state(BirthdayAdminState.message)
                await callback.message.edit_text(
                    "💬 افزودن پیام تبریک\n\n"
                    "متن تبریک را ارسال کن. می‌توانی از متغیرهای زیر استفاده کنی:\n\n"
                    "<code>{name}</code> → نام نمایشی\n"
                    "<code>{first_name}</code> → نام کوچک\n"
                    "<code>{username}</code> → یوزرنیم بدون @\n"
                    "<code>{mention}</code> → منشن قابل کلیک\n"
                    "<code>{user_id}</code> → آیدی عددی تلگرام\n"
                    "<code>{birthday}</code> → تاریخ تولد\n"
                    "<code>{age}</code> → سن (اگر سال تولد ثبت شده باشد)\n\n"
                    "مثال:\n"
                    "🎂 تولدت مبارک {mention} عزیز!\n"
                    "امیدواریم سال جدید زندگیت پر از اتفاق‌های خوب باشه. 🎉\n\n"
                    "برای لغو: /cancel",
                    parse_mode="HTML",
                )
            elif action.startswith("birthday:show:"):
                message_id = int(action.split(":")[-1])
                item = await session.get(BirthdayMessageTemplate, message_id)
                if not item:
                    await callback.answer("پیام پیدا نشد.", show_alert=True)
                    return
                await callback.message.edit_text(
                    f"💬 پیام #{item.id}\n\n{item.text}",
                    reply_markup=birthday_message_item_keyboard(item.id),
                )
            elif action.startswith("birthday:delete:"):
                message_id = int(action.split(":")[-1])
                item = await session.get(BirthdayMessageTemplate, message_id)
                if item:
                    await session.delete(item)
                    await session.commit()
                messages = list((await session.execute(
                    select(BirthdayMessageTemplate).order_by(BirthdayMessageTemplate.id)
                )).scalars().all())
                await callback.message.edit_text(
                    "🗑 پیام حذف شد.",
                    reply_markup=birthday_message_list_keyboard(messages),
                )
        await callback.answer()
        return
    async with session_factory() as session:
        if action == "dashboard":
            users = await session.scalar(select(func.count(User.id))) or 0
            groups = await session.scalar(select(func.count(Group.id)).where(Group.is_active.is_(True))) or 0
            active_games = await session.scalar(select(func.count(Game.id)).where(Game.status.in_(["waiting", "draft", "running"]))) or 0
            finished_games = await session.scalar(select(func.count(Game.id)).where(Game.status == "finished")) or 0
            scenarios = await session.scalar(select(func.count(Scenario.id)).where(Scenario.enabled.is_(True))) or 0
            text = ("🛠 داشبورد مدیریت\n\n"
                    f"👤 کاربران: {users}\n"
                    f"👥 گروه‌های فعال: {groups}\n"
                    f"🎮 بازی‌های فعال: {active_games}\n"
                    f"🏁 بازی‌های تمام‌شده: {finished_games}\n"
                    f"🎭 سناریوهای فعال: {scenarios}")
            await callback.message.edit_text(text, reply_markup=admin_panel_menu())
        elif action == "groups":
            rows = (await session.execute(select(Group).order_by(desc(Group.updated_at)).limit(20))).scalars().all()
            lines = ["👥 گروه‌های ثبت‌شده", ""]
            lines.extend(f"{i}. {g.title or g.telegram_id} — {'فعال' if g.is_active else 'غیرفعال'}" for i, g in enumerate(rows, 1))
            await callback.message.edit_text("\n".join(lines) if rows else "هنوز گروهی ثبت نشده است.", reply_markup=admin_panel_menu())
        elif action == "scenarios":
            scenarios = (await session.execute(select(Scenario).where(Scenario.key != "classic").order_by(Scenario.id))).scalars().all()
            await callback.message.edit_text("🎭 مدیریت سناریوها\n\nوضعیت هر سناریو را انتخاب کنید.", reply_markup=admin_scenario_keyboard(scenarios))
        elif action == "scenario_toggle":
            pass
        elif action == "games":
            rows = (await session.execute(select(Game, Scenario).join(Scenario, Scenario.id == Game.scenario_id).order_by(desc(Game.id)).limit(15))).all()
            lines = ["🎮 بازی‌های اخیر", ""]
            for game, scenario in rows:
                lines.append(f"#{game.id} — {scenario.name_fa} — {_status_fa(game.status)} / {_phase_fa(game.phase)}")
            await callback.message.edit_text("\n".join(lines) if rows else "بازی‌ای ثبت نشده است.", reply_markup=admin_panel_menu())
        elif action == "settings":
            settings = get_settings()
            await callback.message.edit_text(
                "⚙️ تنظیمات ربات\n\n"
                f"حالت اجرا: {'Webhook' if settings.webhook_mode else 'Polling'}\n"
                f"سطح لاگ: {settings.log_level}\n"
                f"تعداد مدیران ربات: {len(settings.admin_id_set)}",
                reply_markup=admin_panel_menu(),
            )
        elif action.startswith("scenario_toggle:"):
            scenario_id = int(action.split(":", 1)[1])
            scenario = await session.get(Scenario, scenario_id)
            if not scenario:
                await callback.answer("سناریو پیدا نشد.", show_alert=True)
                return
            scenario.enabled = not scenario.enabled
            await session.commit()
            scenarios = (await session.execute(select(Scenario).where(Scenario.key != "classic").order_by(Scenario.id))).scalars().all()
            await callback.message.edit_text("🎭 مدیریت سناریوها\n\nوضعیت هر سناریو را انتخاب کنید.", reply_markup=admin_scenario_keyboard(scenarios))
        else:
            await callback.answer("بخش مدیریت ناشناخته است.", show_alert=True)
            return
    await callback.answer()


@router.callback_query(lambda c: c.data == "menu:close")
async def menu_close(callback: CallbackQuery) -> None:
    if callback.message:
        try:
            await callback.message.delete()
        except Exception:
            try:
                await callback.message.edit_text("منو بسته شد.")
            except Exception:
                pass
    await callback.answer()


@router.callback_query(lambda c: c.data == "menu:root")
async def menu_root(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    show_admin = callback.message.chat.type == "private" and callback.from_user.id in get_settings().admin_id_set
    await callback.message.edit_text("منوی اصلی", reply_markup=main_menu(show_admin=show_admin))
    await callback.answer()


@router.callback_query(lambda c: c.data == "menu:group_management")
async def menu_group_management(callback: CallbackQuery) -> None:
    if not callback.message:
        return
    await callback.message.edit_text(
        "مدیریت گروه\n\nبخش موردنظر را انتخاب کنید.",
        reply_markup=group_management_menu(),
    )
    await callback.answer()


@router.callback_query(lambda c: c.data == "menu:active_game")
async def menu_active_game(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    async with session_factory() as session:
        groups = await _manageable_groups(session, callback.bot, callback.from_user.id)
        if not groups:
            await callback.message.edit_text(
                "هیچ گروه فعالی پیدا نشد که هم شما مدیر آن باشید و هم ربات در آن فعال باشد.",
                reply_markup=main_menu(),
            )
        else:
            await callback.message.edit_text(
                "گروه موردنظر را برای مدیریت بازی فعال انتخاب کنید:",
                reply_markup=group_list_keyboard(groups, "active", "menu:root"),
            )
    await callback.answer()


async def _ensure_group_settings(session, group: Group) -> GroupSettings:
    settings = await session.scalar(select(GroupSettings).where(GroupSettings.group_id == group.id))
    if settings is None:
        settings = GroupSettings(group_id=group.id)
        session.add(settings)
        await session.flush()
    return settings


@router.callback_query(lambda c: c.data in {"groupmgmt:defaults", "groupmgmt:players", "groupmgmt:notifications", "groupmgmt:birthday", "groupmgmt:lobby_media", "groupmgmt:invitation", "groupmgmt:scenario"})
async def group_management_settings_entry(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    purpose = callback.data.split(":", 1)[1]
    async with session_factory() as session:
        groups = await _manageable_groups(session, callback.bot, callback.from_user.id)
        if not groups:
            await callback.message.edit_text("هیچ گروه قابل مدیریتی پیدا نشد.", reply_markup=group_management_menu())
        else:
            titles = {
                "defaults": "گروه را برای تنظیمات پایه انتخاب کنید:",
                "players": "گروه را برای تنظیمات بازیکنان انتخاب کنید:",
                "notifications": "گروه را برای تنظیمات اعلان‌ها انتخاب کنید:",
                "birthday": "گروه را برای مدیریت پیام تبریک تولد انتخاب کنید:",
                "lobby_media": "گروه را برای تنظیم رسانه لابی انتخاب کنید:",
                "invitation": "گروه را برای مدیریت دعوت به بازی انتخاب کنید:",
                "scenario": "گروه را برای مدیریت سناریو انتخاب کنید:",
            }
            await callback.message.edit_text(titles[purpose], reply_markup=group_list_keyboard(groups, purpose))
    await callback.answer()


@router.callback_query(lambda c: c.data in {"groupmgmt:achievements", "groupmgmt:tags"})
async def group_management_achievements_tags(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    purpose = "achievements" if callback.data.endswith("achievements") else "tags"
    async with session_factory() as session:
        groups = await _manageable_groups(session, callback.bot, callback.from_user.id)
        if not groups:
            await callback.message.edit_text(
                "هیچ گروه قابل مدیریتی پیدا نشد.",
                reply_markup=group_management_menu(),
            )
        else:
            title = "گروه را برای مدیریت دستاوردها انتخاب کنید:" if purpose == "achievements" else "گروه را برای مدیریت تگ‌ها انتخاب کنید:"
            await callback.message.edit_text(
                title,
                reply_markup=group_list_keyboard(groups, purpose),
            )
    await callback.answer()


@router.callback_query(lambda c: c.data == "groupmgmt:games")
async def group_management_games(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    async with session_factory() as session:
        groups = await _manageable_groups(session, callback.bot, callback.from_user.id)
        if not groups:
            text = "هیچ گروه فعالی پیدا نشد که هم شما مدیر آن باشید و هم ربات در آن فعال باشد."
            await callback.message.edit_text(text, reply_markup=group_management_menu())
        else:
            await callback.message.edit_text(
                "گروه موردنظر را برای مدیریت بازی انتخاب کنید:",
                reply_markup=group_list_keyboard(groups, "active", "menu:group_management"),
            )
    await callback.answer()


@router.callback_query(lambda c: c.data == "groupmgmt:locks")
async def group_management_locks(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    async with session_factory() as session:
        groups = await _manageable_groups(session, callback.bot, callback.from_user.id)
        if not groups:
            await callback.message.edit_text(
                "گروه فعالی برای مدیریت قفل‌ها پیدا نشد.",
                reply_markup=group_management_menu(),
            )
        else:
            await callback.message.edit_text(
                "گروه موردنظر را برای تنظیم قفل‌ها انتخاب کنید:",
                reply_markup=group_list_keyboard(groups, "locks"),
            )
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("groupmgmt:scenario_select:"))
async def group_scenario_select(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.message or not callback.from_user:
        return
    try:
        group_id = int(callback.data.rsplit(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("درخواست نامعتبر است.", show_alert=True)
        return
    async with session_factory() as session:
        group = await _selected_group(session, callback.bot, callback.from_user.id, group_id)
        if not group:
            await callback.answer("دسترسی مدیریت این گروه تأیید نشد.", show_alert=True)
            return
        scenarios = list((await session.execute(
            select(Scenario).where(Scenario.enabled.is_(True), Scenario.key != "classic").order_by(Scenario.id)
        )).scalars().all())
        await state.update_data(group_scenario_group_id=group.id)
        if not scenarios:
            await callback.message.edit_text(
                "❌ هیچ سناریوی فعالی برای این گروه وجود ندارد.",
                reply_markup=group_scenario_management_menu(group.id, scenarios),
            )
        else:
            await callback.message.edit_text(
                "🎭 <b>انتخاب سناریوی پیش‌فرض گروه</b>\n\nسناریوی موردنظر را انتخاب کن:",
                reply_markup=group_default_scenario_keyboard(group.id, scenarios),
                parse_mode="HTML",
            )
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("groupmgmt:scenario_list:"))
async def group_scenario_list(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.message or not callback.from_user:
        return
    try:
        group_id = int(callback.data.rsplit(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("درخواست نامعتبر است.", show_alert=True)
        return
    async with session_factory() as session:
        group = await _selected_group(session, callback.bot, callback.from_user.id, group_id)
        if not group:
            await callback.answer("دسترسی مدیریت این گروه تأیید نشد.", show_alert=True)
            return
        rows = list((await session.execute(
            select(Scenario).where(Scenario.enabled.is_(True), Scenario.key != "classic").order_by(Scenario.id)
        )).scalars().all())
        await state.update_data(group_scenario_group_id=group.id)
        if not rows:
            text = "📚 هیچ سناریوی فعالی ثبت نشده است."
        else:
            text = "📚 <b>سناریوهای فعال گروه</b>\n\n" + "\n".join(
                f"🎭 <b>{escape(s.name_fa)}</b> — {s.max_players} بازیکن" for s in rows
            )
        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(text="🎭 انتخاب سناریوی پیش‌فرض", callback_data=f"groupmgmt:scenario_select:{group.id}"))
        builder.row(InlineKeyboardButton(text="↩️ بازگشت", callback_data=f"groupmgmt:select:scenario:{group.id}"))
        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("groupmgmt:select:"))
async def select_group(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.message or not callback.from_user:
        return
    parts = callback.data.split(":")
    purpose = parts[2] if len(parts) == 4 else "games"
    group_id = int(parts[-1])
    async with session_factory() as session:
        group = await _selected_group(session, callback.bot, callback.from_user.id, group_id)
        if not group:
            await callback.answer("دسترسی مدیریت این گروه تأیید نشد.", show_alert=True)
            return
        if purpose == "locks":
            settings = await _ensure_group_settings(session, group)
            await session.commit()
            await callback.message.edit_text(
                f"🔒 قفل‌های گروه «{group.title or group.telegram_id}»",
                reply_markup=group_lock_keyboard(group.id, settings),
            )
        elif purpose == "defaults":
            settings = await _ensure_group_settings(session, group)
            await session.commit()
            await callback.message.edit_text(
                f"⚙️ تنظیمات پایه «{group.title or group.telegram_id}»",
                reply_markup=group_default_settings_menu(group.id, settings),
            )
        elif purpose == "players":
            settings = await _ensure_group_settings(session, group)
            await session.commit()
            await callback.message.edit_text(
                f"👥 تنظیمات بازیکنان «{group.title or group.telegram_id}»",
                reply_markup=group_player_settings_menu(group.id, settings),
            )
        elif purpose == "notifications":
            settings = await _ensure_group_settings(session, group)
            await session.commit()
            await callback.message.edit_text(
                f"🔔 اعلان‌های «{group.title or group.telegram_id}»",
                reply_markup=group_notification_settings_menu(group.id, settings),
            )
        elif purpose == "achievements":
            from app.services.stats import ensure_achievements
            await ensure_achievements(session)
            achievements = list((await session.execute(select(Achievement).order_by(Achievement.id))).scalars().all())
            await session.commit()
            await callback.message.edit_text(
                "🏆 <b>مدیریت دستاوردها</b>\n\nاموجی فعلی هر دستاورد کنار نامش نمایش داده می‌شود.",
                reply_markup=group_achievement_emoji_menu(group.id, achievements, "groupmgmt:achievements"),
                parse_mode="HTML",
            )
        elif purpose == "tournaments":
            await callback.message.edit_text("🏆 مدیریت تورنمنت‌ها", reply_markup=tournament_admin_menu(group.id))
        elif purpose == "birthday":
            settings = await _ensure_group_settings(session, group)
            await session.commit()
            await callback.message.edit_text(
                f"🎂 <b>مدیریت تولدهای «{escape(group.title or str(group.telegram_id))}»</b>\n\n"
                "از این بخش تنظیمات پیش‌فرض تبریک تولد گروه و ثبت تولد بازیکنان را مدیریت می‌کنی.",
                reply_markup=group_birthday_menu(group.id, settings),
                parse_mode="HTML",
            )
        elif purpose == "scenario":
            scenarios = list((await session.execute(
                select(Scenario).where(Scenario.enabled.is_(True), Scenario.key != "classic").order_by(Scenario.id)
            )).scalars().all())
            settings = await _ensure_group_settings(session, group)
            current = await session.get(Scenario, settings.default_scenario_id) if settings.default_scenario_id else None
            lines = [
                f"🎭 <b>مدیریت سناریو «{escape(group.title or str(group.telegram_id))}»</b>",
                "",
                f"📌 سناریوی پیش‌فرض: <b>{escape(current.name_fa) if current else 'انتخاب نشده'}</b>",
                "",
                "از این بخش می‌توانی سناریوی پیش‌فرض گروه را انتخاب کنی. فقط سناریوهای فعال نمایش داده می‌شوند."
            ]
            await session.commit()
            await state.update_data(group_scenario_group_id=group.id)
            await callback.message.edit_text(
                "\n".join(lines),
                reply_markup=group_scenario_management_menu(group.id, scenarios),
                parse_mode="HTML",
            )
        elif purpose == "invitation":
            setting = await session.scalar(select(GroupInvitationSetting).where(GroupInvitationSetting.group_id == group.id))
            count = await session.scalar(select(func.count()).select_from(GroupInvitationException).where(GroupInvitationException.group_id == group.id)) or 0
            await callback.message.edit_text(
                f"📨 <b>دعوت به بازی «{escape(group.title or str(group.telegram_id))}»</b>\n\n"
                "از این بخش می‌توانی پیام دعوت را برای کاربران فعال ربات در این گروه ارسال کنی.",
                reply_markup=group_invitation_menu(group.id, bool(setting and setting.default_message), int(count)),
                parse_mode="HTML",
            )
        elif purpose == "lobby_media":
            settings = await _ensure_group_settings(session, group)
            await session.commit()
            await callback.message.edit_text(
                f"🎬 <b>رسانه لابی «{group.title or group.telegram_id}»</b>\\n\\n"
                "اگر رسانه سفارشی ثبت نشود، عکس پروفایل گروه به‌صورت خودکار استفاده می‌شود.\\n"
                "با خاموش‌کردن گزینه، لابی بدون عکس/ویدیو ارسال می‌شود.",
                reply_markup=group_lobby_media_menu(group.id, settings),
                parse_mode="HTML",
            )
        elif purpose == "tags":
            from app.services.stats import ensure_achievements
            await ensure_achievements(session)
            tags = list((await session.execute(select(Achievement).where(Achievement.tag_key.is_not(None)).order_by(Achievement.id))).scalars().all())
            await session.commit()
            await callback.message.edit_text(
                "🏷️ <b>مدیریت تگ‌ها</b>\n\nاموجی فعلی هر تگ کنار نامش نمایش داده می‌شود.",
                reply_markup=group_tag_emoji_menu(group.id, tags, "groupmgmt:tags"),
                parse_mode="HTML",
            )
        elif purpose == "active":
            game = await GameRepository.get_active(session, group.id)
            if not game:
                await callback.message.edit_text(
                    f"گروه: {group.title or group.telegram_id}\n\nدر حال حاضر بازی فعالی وجود ندارد.",
                    reply_markup=group_management_menu(),
                )
            else:
                scenario = await session.get(Scenario, game.scenario_id)
                await callback.message.edit_text(
                    f"مدیریت بازی فعال\nگروه: {group.title or group.telegram_id}\n"
                    f"سناریو: {scenario.name_fa if scenario else 'نامشخص'}\n"
                    f"وضعیت: {_status_fa(game.status)}\nمرحله: {_phase_fa(game.phase)}",
                    reply_markup=active_game_menu(group.id, "groupmgmt:games", game.game_key, game.status == "waiting"),
                )
        else:
            await callback.message.edit_text(
                f"گروه: {group.title or group.telegram_id}\n\nبخش موردنظر را انتخاب کنید.",
                reply_markup=group_game_menu(group.id),
            )
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("groupbirthday:"))
async def group_birthday_defaults_handler(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.message or not callback.from_user:
        return
    parts = callback.data.split(":")
    if len(parts) < 3:
        await callback.answer("درخواست نامعتبر است.", show_alert=True)
        return
    action = parts[1]
    try:
        group_id = int(parts[2])
    except ValueError:
        await callback.answer("درخواست نامعتبر است.", show_alert=True)
        return
    async with session_factory() as session:
        group = await _selected_group(session, callback.bot, callback.from_user.id, group_id)
        if not group:
            await callback.answer("دسترسی مدیریت این گروه تأیید نشد.", show_alert=True)
            return
        settings = await _ensure_group_settings(session, group)
        if action == "toggle" and len(parts) == 4:
            field = parts[3]
            if field not in {"birthday_enabled", "birthday_media_enabled"}:
                await callback.answer("تنظیم نامعتبر است.", show_alert=True)
                return
            setattr(settings, field, not bool(getattr(settings, field)))
            await session.commit()
        elif action == "media":
            await state.clear()
            await state.update_data(group_id=group.id)
            await state.set_state(GroupBirthdayDefaultState.media)
            await callback.message.edit_text(
                "📤 رسانه پیش‌فرض گروه را ارسال کن.\n\nعکس یا ویدیو قابل ثبت است.\nبرای لغو /cancel",
            )
            await callback.answer()
            return
        elif action == "message":
            await state.clear()
            await state.update_data(group_id=group.id)
            await state.set_state(GroupBirthdayDefaultState.message)
            await callback.message.edit_text(
                "📝 پیام تبریک پیش‌فرض گروه را ارسال کن.\n\n"
                "متغیرهای {name}، {mention}، {username} و {age} قابل استفاده هستند.\n"
                "برای لغو /cancel",
            )
            await callback.answer()
            return
        await callback.message.edit_text(
            f"🎂 <b>پیام تبریک تولد</b> — {escape(group.title or str(group.telegram_id))}\n\n"
            "این بخش فقط تنظیمات پیش‌فرض گروه را کنترل می‌کند.",
            reply_markup=group_birthday_menu(group.id, settings),
            parse_mode="HTML",
        )
    await callback.answer("ذخیره شد.")


@router.callback_query(lambda c: c.data.startswith("groupmgmt:birthday_add:"))
async def group_birthday_add(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.message or not callback.from_user:
        return
    try:
        group_id = int(callback.data.rsplit(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("درخواست نامعتبر است.", show_alert=True)
        return
    async with session_factory() as session:
        group = await _selected_group(session, callback.bot, callback.from_user.id, group_id)
    if not group:
        await callback.answer("دسترسی مدیریت این گروه تأیید نشد.", show_alert=True)
        return
    await state.clear()
    await state.update_data(group_id=group.id)
    await state.set_state(GroupBirthdayState.input)
    await callback.message.edit_text(
        f"🎂 <b>ثبت / ویرایش تولد</b> — {escape(group.title or str(group.telegram_id))}\n\n"
        "فرمت: <code>آیدی عددی/تاریخ تولد</code>\n"
        "مثال: <code>123456789/10/05</code> یا <code>123456789/2000/10/05</code>\n"
        "برای دریافت تاریخ از پروفایل تلگرام، فقط آیدی عددی را بفرست.\n\n"
        "برای لغو /cancel",
        parse_mode="HTML",
    )
    await callback.answer()

@router.callback_query(lambda c: c.data.startswith("groupmgmt:birthday_list:"))
async def group_birthday_list(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    try:
        group_id = int(callback.data.rsplit(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("درخواست نامعتبر است.", show_alert=True)
        return
    async with session_factory() as session:
        group = await _selected_group(session, callback.bot, callback.from_user.id, group_id)
        if not group:
            await callback.answer("دسترسی مدیریت این گروه تأیید نشد.", show_alert=True)
            return
        users = list((await session.execute(
            select(User).join(GamePlayer, GamePlayer.user_id == User.id)
            .join(Game, Game.id == GamePlayer.game_id)
            .where(
                Game.group_id == group.id,
                User.birthday.is_not(None),
                GamePlayer.is_reserved.is_(False),
            ).distinct().order_by(User.display_name, User.first_name)
        )).scalars().all())
        text = "📋 <b>تولدهای ثبت‌شده این گروه</b>\n\n"
        if not users:
            text += "هنوز تولدی برای بازیکنان این گروه ثبت نشده است."
        else:
            text += "\n".join(
                f"🎂 {tg_mention(u.telegram_id, u.display_name or u.first_name or str(u.telegram_id))} — {birthday_label(u.birthday)}"
                for u in users
            )
        await callback.message.edit_text(
            text,
            reply_markup=group_birthday_list_keyboard(group.id, users),
            parse_mode="HTML",
        )
    await callback.answer()

@router.callback_query(lambda c: c.data.startswith("groupmgmt:birthday_edit:"))
async def group_birthday_edit(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.message or not callback.from_user:
        return
    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer("درخواست نامعتبر است.", show_alert=True)
        return
    group_id, telegram_id = int(parts[2]), int(parts[3])
    async with session_factory() as session:
        group = await _selected_group(session, callback.bot, callback.from_user.id, group_id)
        user = await session.scalar(select(User).where(User.telegram_id == telegram_id)) if group else None
    if not group or not user:
        await callback.answer("کاربر پیدا نشد یا دسترسی ندارید.", show_alert=True)
        return
    await state.clear()
    await state.update_data(group_id=group.id)
    await state.set_state(GroupBirthdayState.input)
    await callback.message.edit_text(
        f"✏️ <b>ویرایش تولد {tg_mention(user.telegram_id, user.display_name or user.first_name or 'بازیکن')}</b>\n\n"
        f"تاریخ فعلی: <b>{birthday_label(user.birthday)}</b>\n"
        "فرمت جدید را بفرست: <code>آیدی/روز/ماه</code> یا <code>آیدی/سال/ماه/روز</code>\n"
        "برای لغو /cancel",
        parse_mode="HTML",
    )
    await callback.answer()

@router.callback_query(lambda c: c.data.startswith("birthday:user:"))
async def birthday_user_customization(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.message or not callback.from_user:
        return
    parts = callback.data.split(":")
    if len(parts) != 5:
        await callback.answer("درخواست نامعتبر است.", show_alert=True)
        return
    _, _, action, group_raw, user_raw = parts
    group_id, telegram_id = int(group_raw), int(user_raw)
    async with session_factory() as session:
        group = await _selected_group(session, callback.bot, callback.from_user.id, group_id)
        user = await session.scalar(select(User).where(User.telegram_id == telegram_id)) if group else None
        if not group or not user:
            await callback.answer("کاربر پیدا نشد یا دسترسی ندارید.", show_alert=True)
            return
        if action == "clear":
            user.birthday_message = None
            user.birthday_media_type = None
            user.birthday_media_file_id = None
            await session.commit()
            await callback.message.edit_reply_markup(
                reply_markup=birthday_user_customization_keyboard(group.id, user.telegram_id, False, False)
            )
            await callback.answer("سفارشی‌سازی تولد پاک شد.")
            return
    await state.clear()
    await state.update_data(group_id=group_id, user_id=telegram_id)
    if action == "message":
        await state.set_state(GroupBirthdayState.message)
        await callback.message.edit_text(
            "📝 <b>پیام سفارشی تولد</b>\n\n"
            "متن را بفرست. متغیرها: {name}، {username}، {mention}، {age}\n"
            "برای حذف پیام سفارشی، <code>-</code> بفرست.\n"
            "برای لغو /cancel",
            parse_mode="HTML",
        )
    elif action == "media":
        await state.set_state(GroupBirthdayState.media)
        await callback.message.edit_text(
            "🖼🎬 <b>رسانه سفارشی تولد</b>\n\n"
            "یک عکس یا ویدیو بفرست. فایل با file_id تلگرام ذخیره می‌شود.\n"
            "برای حذف رسانه <code>-</code> بفرست.\n"
            "برای لغو /cancel",
            parse_mode="HTML",
        )
    else:
        await callback.answer("گزینه نامعتبر است.", show_alert=True)
        return
    await callback.answer()

@router.message(GroupBirthdayDefaultState.message)
async def group_birthday_default_message_save(message: Message, state: FSMContext) -> None:
    if message.chat.type != "private" or not message.from_user:
        return
    raw = (message.text or "").strip()
    data = await state.get_data()
    group_id = int(data.get("group_id", 0))
    if raw == "/cancel":
        await state.clear()
        async with session_factory() as session:
            group = await _selected_group(session, message.bot, message.from_user.id, group_id)
            settings = await _ensure_group_settings(session, group) if group else None
        if group and settings:
            await message.answer("لغو شد.", reply_markup=group_birthday_menu(group_id, settings))
        else:
            await message.answer("لغو شد.", reply_markup=group_management_menu())
        return
    if not raw:
        await message.answer("❌ متن پیام خالی است.")
        return
    unknown = sorted(set(re.findall(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", raw)) - {"name","first_name","username","mention","user_id","birthday","age"})
    if unknown:
        await message.answer("❌ متغیر نامعتبر: " + ", ".join("{" + x + "}" for x in unknown))
        return
    async with session_factory() as session:
        group = await _selected_group(session, message.bot, message.from_user.id, group_id)
        if not group:
            await state.clear()
            await message.answer("❌ دسترسی گروه تأیید نشد.", reply_markup=group_management_menu())
            return
        settings = await _ensure_group_settings(session, group)
        settings.birthday_default_message = raw if raw != "-" else None
        await session.commit()
    await state.clear()
    await message.answer("✅ پیام تبریک پیش‌فرض گروه ذخیره شد.", reply_markup=group_birthday_menu(group_id, settings))


@router.message(GroupBirthdayDefaultState.media)
async def group_birthday_default_media_save(message: Message, state: FSMContext) -> None:
    if message.chat.type != "private" or not message.from_user:
        return
    data = await state.get_data()
    group_id = int(data.get("group_id", 0))
    if (message.text or "").strip() == "/cancel":
        await state.clear()
        async with session_factory() as session:
            group = await _selected_group(session, message.bot, message.from_user.id, group_id)
            settings = await _ensure_group_settings(session, group) if group else None
        if group and settings:
            await message.answer("لغو شد.", reply_markup=group_birthday_menu(group_id, settings))
        else:
            await message.answer("لغو شد.", reply_markup=group_management_menu())
        return
    async with session_factory() as session:
        group = await _selected_group(session, message.bot, message.from_user.id, group_id)
        if not group:
            await state.clear()
            await message.answer("❌ دسترسی گروه تأیید نشد.", reply_markup=group_management_menu())
            return
        settings = await _ensure_group_settings(session, group)
        if (message.text or "").strip() == "-":
            settings.birthday_media_type = None
            settings.birthday_media_file_id = None
        elif message.photo:
            settings.birthday_media_type = "photo"
            settings.birthday_media_file_id = message.photo[-1].file_id
        elif message.video:
            settings.birthday_media_type = "video"
            settings.birthday_media_file_id = message.video.file_id
        else:
            await message.answer("❌ فقط عکس یا ویدیو بفرست؛ یا برای حذف رسانه - ارسال کن.")
            return
        await session.commit()
    await state.clear()
    await message.answer("✅ رسانه پیش‌فرض گروه ذخیره شد.", reply_markup=group_birthday_menu(group_id, settings))


@router.message(GroupBirthdayState.message)
async def group_birthday_message_save(message: Message, state: FSMContext) -> None:
    if message.chat.type != "private" or not message.from_user:
        return
    raw = (message.text or "").strip()
    if raw == "/cancel":
        await state.clear()
        await message.answer("لغو شد.", reply_markup=group_management_menu())
        return
    data = await state.get_data()
    group_id, user_id = int(data.get("group_id", 0)), int(data.get("user_id", 0))
    if not raw:
        await message.answer("❌ متن پیام خالی است.")
        return
    async with session_factory() as session:
        group = await _selected_group(session, message.bot, message.from_user.id, group_id)
        user = await session.scalar(select(User).where(User.telegram_id == user_id)) if group else None
        if not group or not user:
            await state.clear()
            await message.answer("❌ دسترسی یا کاربر نامعتبر است.", reply_markup=group_management_menu())
            return
        if raw == "-":
            user.birthday_message = None
        else:
            unknown = sorted(set(re.findall(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", raw)) - {"name","username","mention","age"})
            if unknown:
                await message.answer("❌ متغیر نامعتبر: " + ", ".join("{" + x + "}" for x in unknown))
                return
            user.birthday_message = raw
        await session.commit()
        has_media = bool(user.birthday_media_file_id)
    await state.clear()
    await message.answer("✅ پیام سفارشی تولد ذخیره شد.", reply_markup=birthday_user_customization_keyboard(group_id, user_id, raw != "-", has_media))

@router.message(GroupBirthdayState.media)
async def group_birthday_media_save(message: Message, state: FSMContext) -> None:
    if message.chat.type != "private" or not message.from_user:
        return
    data = await state.get_data()
    group_id, user_id = int(data.get("group_id", 0)), int(data.get("user_id", 0))
    if (message.text or "").strip() == "/cancel":
        await state.clear()
        await message.answer("لغو شد.", reply_markup=group_management_menu())
        return
    async with session_factory() as session:
        group = await _selected_group(session, message.bot, message.from_user.id, group_id)
        user = await session.scalar(select(User).where(User.telegram_id == user_id)) if group else None
        if not group or not user:
            await state.clear()
            await message.answer("❌ دسترسی یا کاربر نامعتبر است.", reply_markup=group_management_menu())
            return
        if (message.text or "").strip() == "-":
            user.birthday_media_type = None
            user.birthday_media_file_id = None
        elif message.photo:
            user.birthday_media_type = "photo"
            user.birthday_media_file_id = message.photo[-1].file_id
        elif message.video:
            user.birthday_media_type = "video"
            user.birthday_media_file_id = message.video.file_id
        else:
            await message.answer("❌ فقط عکس یا ویدیو بفرست؛ یا برای حذف رسانه - ارسال کن.")
            return
        await session.commit()
        has_message = bool(user.birthday_message)
        has_media = bool(user.birthday_media_file_id)
    await state.clear()
    await message.answer("✅ رسانه سفارشی تولد ذخیره شد.", reply_markup=birthday_user_customization_keyboard(group_id, user_id, has_message, has_media))

@router.message(GroupBirthdayState.input)
async def group_birthday_save(message: Message, state: FSMContext) -> None:
    if message.chat.type != "private" or not message.from_user:
        return
    raw = (message.text or "").strip()
    if raw == "/cancel":
        await state.clear()
        await message.answer("ثبت تاریخ تولد لغو شد.", reply_markup=group_management_menu())
        return
    telegram_id_text, date_text = (raw.split("/", 1) + [""])[:2] if "/" in raw else (raw, "")
    telegram_id_text = telegram_id_text.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")).strip()
    if not telegram_id_text.isdigit():
        await message.answer("❌ آیدی عددی تلگرام معتبر نیست.")
        return
    birthday = parse_birthday(date_text) if date_text else None
    data = await state.get_data()
    async with session_factory() as session:
        group = await _selected_group(session, message.bot, message.from_user.id, int(data.get("group_id", 0)))
        if not group:
            await state.clear()
            await message.answer("❌ دسترسی مدیریت این گروه تأیید نشد.")
            return
        tg_id = int(telegram_id_text)
        user = await session.scalar(select(User).where(User.telegram_id == tg_id))
        if not user:
            try:
                member = await message.bot.get_chat_member(group.telegram_id, tg_id)
                user = await sync_telegram_user(
                    session, member.user.id, member.user.username,
                    member.user.first_name or "", member.user.last_name
                )
            except Exception:
                await message.answer("❌ کاربر با این آیدی در این گروه پیدا نشد یا ربات به اطلاعات او دسترسی ندارد.")
                return
        if not birthday:
            birthday = user.birthday or await get_telegram_profile_birthday(message.bot, tg_id)
            if not birthday:
                await message.answer("❌ تاریخ تولد این کاربر در پروفایل ربات ثبت نشده و از پروفایل تلگرام هم قابل دریافت نیست.")
                return
        user.birthday = birthday
        await session.commit()
    await state.clear()
    await message.answer(
        f"✅ تاریخ تولد {tg_mention(tg_id, user.display_name or user.first_name)} ثبت شد: {birthday_label(birthday)}\n\n"
        "حالا می‌توانی برای همین بازیکن پیام یا رسانه سفارشی تعیین کنی.",
        reply_markup=birthday_user_customization_keyboard(
            int(data.get("group_id", 0)),
            tg_id,
            bool(user.birthday_message),
            bool(user.birthday_media_file_id),
        ),
        parse_mode="HTML",
    )


async def _ensure_invitation_setting(session, group_id: int) -> GroupInvitationSetting:
    setting = await session.scalar(select(GroupInvitationSetting).where(GroupInvitationSetting.group_id == group_id))
    if setting is None:
        setting = GroupInvitationSetting(group_id=group_id)
        session.add(setting)
        await session.flush()
    return setting


def _render_invitation_message(template: str, user: User) -> str:
    username = str(user.username or "").strip().lstrip("@")
    display_name = str(user.display_name or user.first_name or "").strip()
    first_name = str(user.first_name or display_name or "").strip()
    values = {
        "{name}": display_name,
        "{first_name}": first_name,
        "{username}": ("@" + username) if username else display_name,
        "{mention}": ("@" + username) if username else display_name,
        "{user_id}": str(user.telegram_id),
    }
    rendered = str(template or "")
    for placeholder, value in values.items():
        rendered = rendered.replace(placeholder, value)
    return rendered


async def _invitation_recipients(session, group_id: int):
    excluded = set((await session.execute(
        select(GroupInvitationException.user_id).where(GroupInvitationException.group_id == group_id)
    )).scalars().all())
    users = list((await session.execute(
        select(User).join(GamePlayer, GamePlayer.user_id == User.id).join(Game, Game.id == GamePlayer.game_id)
        .where(Game.group_id == group_id, User.is_active.is_(True)).distinct()
    )).scalars().all())
    return [u for u in users if u.id not in excluded]


async def _show_invitation_menu(callback: CallbackQuery, group_id: int) -> None:
    async with session_factory() as session:
        group = await _selected_group(session, callback.bot, callback.from_user.id, group_id)
        if not group:
            await callback.answer("دسترسی مدیریت گروه تأیید نشد.", show_alert=True)
            return
        setting = await session.scalar(select(GroupInvitationSetting).where(GroupInvitationSetting.group_id == group.id))
        count = await session.scalar(select(func.count()).select_from(GroupInvitationException).where(GroupInvitationException.group_id == group.id)) or 0
        await callback.message.edit_text(
            f"📨 <b>دعوت به بازی «{escape(group.title or str(group.telegram_id))}»</b>\n\n"
            "پیام دعوت را مدیریت یا برای کاربران فعال ربات ارسال کن.",
            reply_markup=group_invitation_menu(group.id, bool(setting and setting.default_message), int(count)),
            parse_mode="HTML",
        )


@router.callback_query(lambda c: c.data.startswith("invitation:"))
async def group_invitation_handler(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.message or not callback.from_user:
        return
    parts = callback.data.split(":")
    action = parts[1] if len(parts) > 1 else ""
    try:
        group_id = int(parts[-1]) if action != "exception_remove" else int(parts[2])
    except (ValueError, IndexError):
        await callback.answer("درخواست نامعتبر است.", show_alert=True)
        return
    async with session_factory() as session:
        group = await _selected_group(session, callback.bot, callback.from_user.id, group_id)
        if not group:
            await callback.answer("دسترسی مدیریت گروه تأیید نشد.", show_alert=True)
            return
        setting = await _ensure_invitation_setting(session, group.id)
        if action == "menu":
            await session.commit()
            await _show_invitation_menu(callback, group.id)
            return
        if action in {"button_yes", "button_no"}:
            mode = parts[2] if len(parts) > 2 else "default"
            data = await state.get_data()
            text_value = setting.default_message if mode == "default" else data.get("message")
            if not text_value:
                await callback.answer("متن پیام پیدا نشد.", show_alert=True)
                return
            enabled = action == "button_yes"
            if mode in {"default", "edit"}:
                setting.default_message = text_value
                setting.invite_button_enabled = enabled
                setting.invite_button_text = "🎮 ورود به بازی"
                await session.commit()
            else:
                await state.update_data(invite_button_enabled=enabled)
            await callback.message.edit_text(
                f"📨 <b>پیش‌نمایش پیام دعوت</b>\n\n{escape(text_value)}\n\n"
                + ("🔗 دکمه لینک دعوت هم اضافه می‌شود." if enabled else "بدون دکمه ارسال می‌شود.")
                + "\n\nدر صورت تأیید، پیام برای کاربران فعال ربات ارسال می‌شود.",
                reply_markup=invitation_confirm_keyboard(group.id, "default" if mode in {"default", "edit"} else "custom"),
                parse_mode="HTML",
            )
            await callback.answer()
            return
        if action == "send":
            await session.commit()
            await callback.message.edit_text("📤 <b>ارسال پیام دعوت</b>\n\nروش ارسال را انتخاب کن:", reply_markup=group_invitation_send_menu(group.id, bool(setting.default_message)), parse_mode="HTML")
            await callback.answer()
            return
        if action == "missing_default":
            await session.commit()
            await callback.message.edit_text("❌ پیام پیش‌فرضی ثبت نشده است.\n\nمی‌توانی همین حالا یک پیام ایجاد کنی:", reply_markup=group_invitation_send_menu(group.id, False))
            await callback.answer()
            return
        if action == "show":
            if not setting.default_message:
                await callback.message.edit_text("❌ هنوز پیام پیش‌فرضی ثبت نشده است.", reply_markup=group_invitation_send_menu(group.id, False))
            else:
                await callback.message.edit_text(f"📌 <b>پیام پیش‌فرض دعوت</b>\n\n{escape(setting.default_message)}", reply_markup=invitation_copy_keyboard(setting.default_message), parse_mode="HTML")
            await session.commit()
            await callback.answer()
            return
        if action == "edit":
            await state.clear()
            await state.update_data(group_id=group.id, mode="edit")
            await state.set_state(GroupInvitationState.message)
            current = setting.default_message
            prompt = "متن جدید پیام پیش‌فرض را ارسال کن." if current else "پیام پیش‌فرضی وجود ندارد؛ متن پیام جدید را ارسال کن."
            if current:
                prompt += f"\n\n<b>پیام فعلی:</b>\n{escape(current)}"
            await callback.message.edit_text(f"✏️ <b>ویرایش/ایجاد پیام پیش‌فرض</b>\n\n{prompt}\n\nبرای لغو /cancel", parse_mode="HTML")
            await session.commit()
            await callback.answer()
            return
        if action == "preview_default":
            if not setting.default_message:
                await callback.message.edit_text("❌ پیام پیش‌فرضی وجود ندارد.", reply_markup=group_invitation_send_menu(group.id, False))
            else:
                await callback.message.edit_text(f"📨 <b>پیام آماده ارسال:</b>\n\n{escape(setting.default_message)}\n\nدر صورت تأیید برای کاربران فعال ربات ارسال می‌شود.", reply_markup=invitation_confirm_keyboard(group.id, "default"), parse_mode="HTML")
            await session.commit()
            await callback.answer()
            return
        if action == "create":
            await state.clear()
            await state.update_data(group_id=group.id, mode="create")
            await state.set_state(GroupInvitationState.message)
            await callback.message.edit_text("✍️ <b>ایجاد پیام دعوت</b>\n\nمتن پیام دعوت را ارسال کن.\n\nمتغیرها: {name} نام بازیکن، {first_name} نام کوچک، {username} یوزرنیم، {mention} یوزرنیم یا نام، {user_id} آیدی عددی\nمثال: سلام {name} 👋\n\nبرای لغو /cancel", parse_mode="HTML")
            await session.commit()
            await callback.answer()
            return
        if action == "confirm":
            mode = parts[2] if len(parts) > 2 else "default"
            text_value = setting.default_message if mode == "default" else None
            data = await state.get_data()
            if mode == "custom":
                text_value = data.get("message")
            if not text_value:
                await callback.answer("متن پیام پیدا نشد.", show_alert=True)
                return
            invite_button_enabled = setting.invite_button_enabled if mode == "default" else bool(data.get("invite_button_enabled"))
            recipients = await _invitation_recipients(session, group.id)
            sent = failed = 0
            for user in recipients:
                try:
                    invite_link = None
                    if invite_button_enabled:
                        invite = await callback.bot.create_chat_invite_link(
                            group.telegram_id,
                            name="دعوت یکبارمصرف به بازی",
                            member_limit=1,
                        )
                        invite_link = invite.invite_link
                    await callback.bot.send_message(
                        user.telegram_id,
                        _render_invitation_message(text_value, user),
                        reply_markup=(
                            InlineKeyboardMarkup(
                                inline_keyboard=[[
                                    InlineKeyboardButton(
                                        text=setting.invite_button_text or "🎮 ورود به بازی",
                                        url=invite_link,
                                    )
                                ]]
                            )
                            if invite_link else None
                        ),
                    )
                    sent += 1
                except Exception:
                    failed += 1
            excluded_count = await session.scalar(select(func.count()).select_from(GroupInvitationException).where(GroupInvitationException.group_id == group.id)) or 0
            await session.commit()
            await state.clear()
            await callback.message.edit_text(f"✅ <b>ارسال دعوت انجام شد.</b>\n\n📨 موفق: {sent}\n⚠️ ناموفق: {failed}\n🚫 مستثنی: {excluded_count}", reply_markup=group_invitation_menu(group.id, bool(setting.default_message), int(excluded_count)), parse_mode="HTML")
            await callback.answer()
            return
        if action == "exceptions":
            count = await session.scalar(select(func.count()).select_from(GroupInvitationException).where(GroupInvitationException.group_id == group.id)) or 0
            await callback.message.edit_text("🚫 <b>استثناهای دعوت به بازی</b>\n\nبازیکنان ثبت‌شده در این لیست پیام دعوت دریافت نمی‌کنند.", reply_markup=group_invitation_exception_menu(group.id, int(count)), parse_mode="HTML")
            await session.commit()
            await callback.answer()
            return
        if action == "exception_list":
            rows = list((await session.execute(select(User).join(GroupInvitationException, GroupInvitationException.user_id == User.id).where(GroupInvitationException.group_id == group.id).order_by(User.display_name))).scalars().all())
            if not rows:
                await callback.message.edit_text("🚫 <b>لیست استثناها خالی است.</b>", reply_markup=group_invitation_exception_menu(group.id, 0), parse_mode="HTML")
            else:
                text_value = "🚫 <b>بازیکنان مستثنی</b>\n\n" + "\n".join(f"• {escape(u.display_name or u.first_name or str(u.telegram_id))}" for u in rows)
                await callback.message.edit_text(text_value, reply_markup=group_invitation_exception_list_menu(group.id, rows), parse_mode="HTML")
            await session.commit()
            await callback.answer()
            return
        if action == "exception_remove":
            try:
                user_id = int(parts[3])
            except (ValueError, IndexError):
                await callback.answer("کاربر نامعتبر است.", show_alert=True)
                return
            await session.execute(GroupInvitationException.__table__.delete().where(GroupInvitationException.group_id == group.id, GroupInvitationException.user_id == user_id))
            await session.commit()
            await callback.answer("از لیست استثنا حذف شد.")
            await _show_invitation_menu(callback, group.id)
            return
        if action == "exception_add":
            await state.clear()
            await state.update_data(group_id=group.id)
            await state.set_state(GroupInvitationState.exception)
            await callback.message.edit_text("➕ <b>ایجاد استثنا</b>\n\nآیدی عددی، @username یا فوروارد پیام کاربر را ارسال کن.\n\nبرای لغو /cancel", parse_mode="HTML")
            await session.commit()
            await callback.answer()
            return
        await session.commit()
        await callback.answer()


@router.message(GroupInvitationState.message)
async def group_invitation_message_save(message: Message, state: FSMContext) -> None:
    if message.chat.type != "private" or not message.from_user:
        return
    raw = (message.text or "").strip()
    if not raw:
        await message.answer("❌ متن پیام خالی است.")
        return
    if raw.casefold() == "/cancel":
        await state.clear()
        await message.answer("عملیات دعوت لغو شد.")
        return
    data = await state.get_data()
    group_id = int(data.get("group_id", 0) or 0)
    mode = data.get("mode", "create")
    async with session_factory() as session:
        group = await _selected_group(session, message.bot, message.from_user.id, group_id)
        if not group:
            await state.clear()
            await message.answer("❌ دسترسی مدیریت گروه تأیید نشد.")
            return
        setting = await _ensure_invitation_setting(session, group.id)
        if mode == "edit":
            setting.default_message = raw
            await session.commit()
            await state.clear()
            count = await session.scalar(select(func.count()).select_from(GroupInvitationException).where(GroupInvitationException.group_id == group.id)) or 0
            await message.answer("✅ پیام پیش‌فرض ذخیره شد.", reply_markup=group_invitation_menu(group.id, True, int(count)))
            return
        await state.update_data(message=raw)
        await message.answer("🔗 آیا می‌خواهی زیر پیام یک دکمه با لینک دعوت به گروه هم قرار بگیرد؟", reply_markup=invitation_button_choice_keyboard(group.id, mode))


async def _resolve_invitation_user(message: Message, group: Group):
    raw = (message.text or "").strip()
    async with session_factory() as session:
        if raw:
            normalized = raw.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"))
            if normalized.isdigit():
                user = await session.scalar(select(User).where(User.telegram_id == int(normalized)))
                if user:
                    return user
                try:
                    member = await message.bot.get_chat_member(group.telegram_id, int(normalized))
                    return await sync_telegram_user(session, member.user.id, member.user.username, member.user.first_name or "", member.user.last_name)
                except Exception:
                    return None
            return await session.scalar(select(User).where(func.lower(User.username) == raw.lstrip("@").casefold()))
        origin = getattr(message, "forward_origin", None)
        forwarded_user = getattr(origin, "sender_user", None) if origin else None
        if forwarded_user is None:
            forwarded_user = getattr(message, "forward_from", None) or getattr(message, "forward_from_user", None)
        if forwarded_user is None:
            return None
        return await sync_telegram_user(session, forwarded_user.id, forwarded_user.username, forwarded_user.first_name or "", forwarded_user.last_name)


@router.message(GroupInvitationState.exception)
async def group_invitation_exception_save(message: Message, state: FSMContext) -> None:
    if message.chat.type != "private" or not message.from_user:
        return
    data = await state.get_data()
    group_id = int(data.get("group_id", 0) or 0)
    if (message.text or "").strip().casefold() == "/cancel":
        await state.clear()
        await message.answer("ایجاد استثنا لغو شد.")
        return
    async with session_factory() as session:
        group = await _selected_group(session, message.bot, message.from_user.id, group_id)
        if not group:
            await state.clear()
            await message.answer("❌ دسترسی مدیریت گروه تأیید نشد.")
            return
        user = await _resolve_invitation_user(message, group)
        if not user:
            await message.answer("❌ کاربر پیدا نشد. آیدی عددی، @username یا فوروارد پیام کاربر را ارسال کن.")
            return
        exists = await session.scalar(select(GroupInvitationException).where(GroupInvitationException.group_id == group.id, GroupInvitationException.user_id == user.id))
        if exists:
            await message.answer("⚠️ این کاربر قبلاً مستثنی شده است.")
            return
        session.add(GroupInvitationException(group_id=group.id, user_id=user.id))
        await session.commit()
        await state.clear()
        count = await session.scalar(select(func.count()).select_from(GroupInvitationException).where(GroupInvitationException.group_id == group.id)) or 0
        await message.answer(f"✅ {escape(user.display_name or user.first_name or str(user.telegram_id))} به استثناها اضافه شد.", reply_markup=group_invitation_exception_menu(group.id, int(count)), parse_mode="HTML")

@router.callback_query(lambda c: c.data.startswith("group_lobby_media:"))
async def group_lobby_media_handler(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.message or not callback.from_user:
        return
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("درخواست نامعتبر است.", show_alert=True)
        return
    action, group_id_raw = parts[1], parts[2]
    try:
        group_id = int(group_id_raw)
    except ValueError:
        await callback.answer("گروه نامعتبر است.", show_alert=True)
        return
    async with session_factory() as session:
        group = await _selected_group(session, callback.bot, callback.from_user.id, group_id)
        if not group:
            await callback.answer("دسترسی مدیریت گروه تأیید نشد.", show_alert=True)
            return
        settings = await _ensure_group_settings(session, group)
        if action == "noop":
            await callback.answer("برای تغییر منبع، عکس یا ویدیو جدید ثبت کن.", show_alert=True)
            return
        if action == "toggle":
            settings.lobby_media_enabled = not bool(settings.lobby_media_enabled)
            await session.commit()
        elif action == "clear":
            settings.lobby_media_file_id = None
            settings.lobby_media_type = None
            await session.commit()
        elif action == "set":
            await state.clear()
            await state.update_data(group_id=group.id)
            await state.set_state(GroupLobbyMediaState.media)
            await callback.message.edit_text(
                f"🎬 رسانه لابی «{group.title or group.telegram_id}»\n\n"
                "یک <b>عکس یا ویدیو</b> همینجا ارسال کن. فقط <code>file_id</code> تلگرام ذخیره می‌شود و فایل دوباره آپلود نخواهد شد.\n\n"
                "برای حذف رسانه سفارشی، /clear را بفرست.\n"
                "برای لغو، /cancel را بفرست.",
                parse_mode="HTML",
            )
            await callback.answer()
            return
        await callback.message.edit_text(
            f"🎬 <b>رسانه لابی «{group.title or group.telegram_id}»</b>\n\n"
            "رسانه سفارشی: " + ("ویدیو" if settings.lobby_media_type == "video" else "عکس" if settings.lobby_media_type == "photo" else "ثبت نشده") + "\n"
            f"وضعیت: {'فعال' if settings.lobby_media_enabled else 'غیرفعال'}\n\n"
            "اگر رسانه سفارشی نداشته باشی، در حالت فعال عکس پروفایل گروه استفاده می‌شود.",
            reply_markup=group_lobby_media_menu(group.id, settings),
            parse_mode="HTML",
        )
    await callback.answer("تنظیمات لابی به‌روزرسانی شد.")


@router.message(GroupLobbyMediaState.media)
async def group_lobby_media_save(message: Message, state: FSMContext) -> None:
    if message.chat.type != "private" or not message.from_user:
        return
    data = await state.get_data()
    group_id = int(data.get("group_id", 0) or 0)
    raw = (message.text or "").strip().lower()
    if raw == "/cancel":
        await state.clear()
        await message.answer("ثبت رسانه لابی لغو شد.")
        return
    if raw == "/clear":
        async with session_factory() as session:
            group = await _selected_group(session, message.bot, message.from_user.id, group_id)
            if not group:
                await state.clear(); await message.answer("دسترسی گروه تأیید نشد."); return
            settings = await _ensure_group_settings(session, group)
            settings.lobby_media_file_id = None
            settings.lobby_media_type = None
            await session.commit()
        await state.clear()
        await message.answer("🧹 رسانه سفارشی حذف شد؛ از این به بعد عکس پروفایل گروه استفاده می‌شود.", reply_markup=group_management_menu())
        return
    media_type = None
    file_id = None
    if message.video:
        media_type, file_id = "video", message.video.file_id
    elif message.photo:
        media_type, file_id = "photo", message.photo[-1].file_id
    if not file_id:
        await message.answer("❌ فقط عکس یا ویدیو بفرست. فایل روی سرور ذخیره نمی‌شود و فقط file_id تلگرام نگه‌داری می‌شود.")
        return
    async with session_factory() as session:
        group = await _selected_group(session, message.bot, message.from_user.id, group_id)
        if not group:
            await state.clear(); await message.answer("دسترسی گروه تأیید نشد."); return
        settings = await _ensure_group_settings(session, group)
        settings.lobby_media_file_id = file_id
        settings.lobby_media_type = media_type
        settings.lobby_media_enabled = True
        await session.commit()
    await state.clear()
    await message.answer(
        f"✅ {'ویدیو' if media_type == 'video' else 'عکس'} لابی ذخیره شد.\n\n"
        "از این به بعد لابی با همان file_id ارسال و هنگام ورود بازیکنان فقط caption/دکمه‌ها ویرایش می‌شود.",
        reply_markup=group_management_menu(),
    )


@router.callback_query(lambda c: c.data.startswith("groupdefaults:"))
async def group_defaults_handler(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.message or not callback.from_user:
        return
    parts = callback.data.split(":")
    action = parts[1] if len(parts) > 1 else ""
    try:
        group_id = int(parts[2])
    except (IndexError, ValueError):
        await callback.answer("درخواست نامعتبر است.", show_alert=True)
        return
    async with session_factory() as session:
        group = await _selected_group(session, callback.bot, callback.from_user.id, group_id)
        if not group:
            await callback.answer("دسترسی گروه تأیید نشد.", show_alert=True)
            return
        settings = await _ensure_group_settings(session, group)

        if action == "toggle" and len(parts) == 4:
            field = parts[3]
            allowed = {
                "default_auto_play", "default_reserve_enabled", "default_challenge_enabled",
                "default_next_host_enabled", "default_next_player_enabled", "default_next_auto_enabled",
                "default_turn_color_enabled",
            }
            if field not in allowed:
                await callback.answer("تنظیم نامعتبر است.", show_alert=True)
                return
            setattr(settings, field, not bool(getattr(settings, field)))
        elif action == "time" and len(parts) == 4:
            kind = parts[3]
            current = {
                "turn": settings.default_turn_seconds,
                "challenge": settings.default_challenge_seconds,
                "extra_challenge": settings.default_extra_challenge_seconds,
            }.get(kind)
            if current is None:
                await callback.answer("نوع زمان نامعتبر است.", show_alert=True)
                return
            from app.handlers.keyboards import duration_keyboard
            await callback.message.edit_text(
                "⏱ زمان موردنظر را انتخاب کنید:",
                reply_markup=duration_keyboard("groupdefaults", group.id, kind, current, f"groupmgmt:select:defaults:{group.id}"),
            )
            await callback.answer()
            return
        elif action == "set_time" and len(parts) == 5:
            kind, value = parts[3], int(parts[4])
            mapping = {
                "turn": "default_turn_seconds",
                "challenge": "default_challenge_seconds",
                "extra_challenge": "default_extra_challenge_seconds",
                "vote_pre": "default_voting_pre_delay_seconds",
                "vote_vote": "default_vote_seconds",
            }
            if kind not in mapping or not 15 <= value <= 600:
                await callback.answer("مقدار زمان نامعتبر است.", show_alert=True)
                return
            setattr(settings, mapping[kind], value)
        elif action == "scenario":
            scenarios = (await session.execute(
                select(Scenario).where(Scenario.enabled.is_(True), Scenario.key != "classic").order_by(Scenario.id)
            )).scalars().all()
            await callback.message.edit_text(
                "🎭 سناریوی پیش‌فرض گروه را انتخاب کنید:",
                reply_markup=group_default_scenario_keyboard(group.id, scenarios),
            )
            await callback.answer()
            return
        elif action == "setscenario" and len(parts) == 4:
            scenario_id = int(parts[3])
            if scenario_id == 0:
                settings.default_scenario_id = None
            else:
                scenario = await session.get(Scenario, scenario_id)
                if not scenario or not scenario.enabled or scenario.key == "classic":
                    await callback.answer("سناریو قابل انتخاب نیست.", show_alert=True)
                    return
                settings.default_scenario_id = scenario.id
        elif action == "visual":
            await callback.message.edit_text(
                "🎨 تنظیمات ظاهری پیش‌فرض",
                reply_markup=group_visual_settings_menu(group.id, settings),
            )
            await callback.answer()
            return
        elif action == "voting":
            await callback.message.edit_text(
                "🗳 تنظیمات رأی‌گیری پیش‌فرض",
                reply_markup=group_voting_settings_menu(group.id, settings),
            )
            await callback.answer()
            return
        elif action == "emoji_menu":
            await callback.message.edit_text(
                "✨ <b>مدیریت اموجی‌های متحرک</b>\n\n"
                "اموجی‌ها بر اساس محل استفاده جدا شده‌اند. اموجی فعلی هر مورد در منوی مربوط نمایش داده می‌شود.\n"
                "برای ثبت یا ویرایش، روی مورد بزن و یک Custom Emoji از پک RestrictedEmoji بفرست.",
                reply_markup=group_custom_emoji_menu(group.id, settings),
                parse_mode="HTML",
            )
            await callback.answer()
            return
        elif action == "emoji_section" and len(parts) == 4:
            section = parts[3]
            if section == "game":
                await callback.message.edit_text(
                    "🎮 <b>اموجی‌های بازی</b>\n\nاموجی هر بخش را انتخاب کن تا ثبت یا ویرایش شود.",
                    reply_markup=group_game_emoji_menu(group.id, settings),
                    parse_mode="HTML",
                )
            elif section == "achievement":
                from app.services.stats import ensure_achievements
                await ensure_achievements(session)
                achievements = list((await session.execute(select(Achievement).order_by(Achievement.id))).scalars().all())
                await session.commit()
                await callback.message.edit_text(
                    "🏆 <b>اموجی دستاوردها</b>\n\nاموجی فعلی هر دستاورد کنار نامش نمایش داده می‌شود.",
                    reply_markup=group_achievement_emoji_menu(group.id, achievements),
                    parse_mode="HTML",
                )
            elif section == "tag":
                from app.services.stats import ensure_achievements
                await ensure_achievements(session)
                tags = list((await session.execute(select(Achievement).where(Achievement.tag_key.is_not(None)).order_by(Achievement.id))).scalars().all())
                await session.commit()
                await callback.message.edit_text(
                    "🏷️ <b>اموجی تگ‌ها</b>\n\nاموجی فعلی هر تگ کنار نامش نمایش داده می‌شود.",
                    reply_markup=group_tag_emoji_menu(group.id, tags),
                    parse_mode="HTML",
                )
            else:
                await callback.answer("بخش اموجی نامعتبر است.", show_alert=True)
                return
            await callback.answer()
            return
        elif action == "emoji_toggle":
            settings.custom_emoji = not settings.custom_emoji
        elif action == "emoji_clear":
            settings.custom_emoji_ids = "{}"
        elif action == "emoji_set" and len(parts) == 4:
            key = parts[3]
            allowed_keys = {"turn", "challenge", "vote", "defense", "silence", "extra_turn", "warning", "death", "kick", "slaughter", "night", "day", "win", "lose", "leader", "game", "role"}
            if key not in allowed_keys:
                await callback.answer("نوع اموجی نامعتبر است.", show_alert=True)
                return
            await state.set_state(CustomEmojiState.emoji)
            await state.update_data(group_id=group.id, emoji_key=key, target_type="game")
            await callback.message.answer(
                "✨ اموجی این بخش را از پک RestrictedEmoji همین‌جا بفرست.\n"
                "ربات شناسه واقعی Custom Emoji را ذخیره می‌کند.\n"
                "برای حذف، /clear بفرست."
            )
            await callback.answer()
            return
        elif action in {"achievement_emoji", "tag_emoji"} and len(parts) == 4:
            key = parts[3]
            achievement = await session.scalar(select(Achievement).where(Achievement.key == key))
            if not achievement:
                await callback.answer("دستاورد/تگ پیدا نشد.", show_alert=True)
                return
            if action == "tag_emoji" and not achievement.tag_key:
                await callback.answer("این مورد تگ ندارد.", show_alert=True)
                return
            await state.set_state(CustomEmojiState.emoji)
            await state.update_data(
                group_id=group.id,
                emoji_key=key,
                target_type="achievement" if action == "achievement_emoji" else "tag",
            )
            label = achievement.name_fa if action == "achievement_emoji" else (achievement.tag_name or achievement.name_fa)
            await callback.message.answer(
                f"✨ اموجی «{label}» را از پک RestrictedEmoji بفرست.\n"
                "این اموجی قبلی را جایگزین می‌کند. برای حذف، /clear بفرست."
            )
            await callback.answer()
            return
        elif action == "achievement_emoji_clear":
            achievements = list((await session.execute(select(Achievement))).scalars().all())
            for achievement in achievements:
                achievement.custom_emoji_id = None
        elif action == "tag_emoji_clear":
            achievements = list((await session.execute(select(Achievement).where(Achievement.tag_key.is_not(None)))).scalars().all())
            for achievement in achievements:
                achievement.tag_custom_emoji_id = None
        elif action == "emoji":
            settings.custom_emoji = not settings.custom_emoji
        elif action == "color" and len(parts) == 4:
            kind = parts[3]
            colors = ["پیش‌فرض", "قرمز", "آبی", "سبز", "زرد", "بنفش"]
            field = "default_turn_color" if kind == "turn" else "default_challenge_color"
            current = getattr(settings, field)
            setattr(settings, field, colors[(colors.index(current) + 1) % len(colors)] if current in colors else colors[0])
        elif action == "toggle_mode" and len(parts) == 4:
            field = "default_voting_mode" if parts[3] == "voting" else "default_vote2_selection_mode"
            setattr(settings, field, "auto" if getattr(settings, field) != "auto" else "manual")
        elif action == "vote_time" and len(parts) == 4:
            kind = parts[3]
            current = settings.default_voting_pre_delay_seconds if kind == "pre" else settings.default_vote_seconds
            from app.handlers.keyboards import duration_keyboard
            await callback.message.edit_text(
                "⏱ زمان رأی را انتخاب کنید:",
                reply_markup=duration_keyboard("groupdefaults", group.id, f"vote_{kind}", current, f"groupmgmt:select:defaults:{group.id}"),
            )
            await callback.answer()
            return
        await session.commit()
        if action in {"visual", "emoji", "color"}:
            markup = group_visual_settings_menu(group.id, settings)
        elif action in {"emoji_menu", "emoji_toggle", "emoji_clear", "achievement_emoji_clear", "tag_emoji_clear"}:
            markup = group_custom_emoji_menu(group.id, settings)
        elif action in {"voting", "toggle_mode"}:
            markup = group_voting_settings_menu(group.id, settings)
        else:
            markup = group_default_settings_menu(group.id, settings)
        await callback.message.edit_text(f"⚙️ تنظیمات پایه «{group.title}»", reply_markup=markup)
    await callback.answer("تنظیم ذخیره شد.")


@router.message(CustomEmojiState.emoji)
async def custom_emoji_capture(message: Message, state: FSMContext) -> None:
    if message.chat.type != "private" or not message.from_user:
        return
    data = await state.get_data()
    group_id = data.get("group_id")
    key = data.get("emoji_key")
    target_type = data.get("target_type", "game")
    if not group_id or not key:
        await state.clear()
        return

    if (message.text or "").strip().lower() == "/clear":
        async with session_factory() as session:
            group = await _selected_group(session, message.bot, message.from_user.id, int(group_id))
            if not group:
                await state.clear()
                await message.answer("دسترسی گروه تأیید نشد.")
                return
            settings = await _ensure_group_settings(session, group)
            if target_type == "achievement":
                achievement = await session.scalar(select(Achievement).where(Achievement.key == key))
                if achievement:
                    achievement.custom_emoji_id = None
            elif target_type == "tag":
                achievement = await session.scalar(select(Achievement).where(Achievement.key == key))
                if achievement:
                    achievement.tag_custom_emoji_id = None
            else:
                mapping = normalize_emoji_map(settings.custom_emoji_ids)
                mapping.pop(key, None)
                settings.custom_emoji_ids = dump_emoji_map(mapping)
            await session.commit()
        await state.clear()
        await message.answer("🧹 اموجی این بخش حذف شد.")
        return

    custom_id = extract_custom_emoji_id(message)
    if not custom_id:
        await message.answer(
            "❌ این پیام Custom Emoji قابل شناسایی ندارد.\n"
            "یک اموجی را مستقیم از پک RestrictedEmoji انتخاب و ارسال کن."
        )
        return

    async with session_factory() as session:
        group = await _selected_group(session, message.bot, message.from_user.id, int(group_id))
        if not group:
            await state.clear()
            await message.answer("دسترسی گروه تأیید نشد.")
            return
        settings = await _ensure_group_settings(session, group)
        if target_type == "achievement":
            achievement = await session.scalar(select(Achievement).where(Achievement.key == key))
            if not achievement:
                await state.clear()
                await message.answer("دستاورد پیدا نشد.")
                return
            achievement.custom_emoji_id = custom_id
            label = achievement.name_fa
        elif target_type == "tag":
            achievement = await session.scalar(select(Achievement).where(Achievement.key == key))
            if not achievement or not achievement.tag_key:
                await state.clear()
                await message.answer("تگ پیدا نشد.")
                return
            achievement.tag_custom_emoji_id = custom_id
            label = achievement.tag_name or achievement.name_fa
        else:
            mapping = normalize_emoji_map(settings.custom_emoji_ids)
            mapping[key] = custom_id
            settings.custom_emoji_ids = dump_emoji_map(mapping)
            settings.custom_emoji = True
            label = key
        await session.commit()

    await state.clear()
    await message.answer(
        f"✅ اموجی متحرک «{label}» ذخیره شد.\n"
        "اموجی قبلی با این مورد جایگزین شد و در صورت خطای Telegram، اموجی معمولی نمایش داده می‌شود."
    )


@router.callback_query(lambda c: c.data.startswith("groupplayers:"))
async def group_players_settings_handler(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    parts = callback.data.split(":")
    try:
        group_id = int(parts[2])
    except (IndexError, ValueError):
        await callback.answer("درخواست نامعتبر است.", show_alert=True)
        return
    async with session_factory() as session:
        group = await _selected_group(session, callback.bot, callback.from_user.id, group_id)
        if not group:
            await callback.answer("دسترسی گروه تأیید نشد.", show_alert=True)
            return
        settings = await _ensure_group_settings(session, group)
        if parts[1] == "toggle" and len(parts) == 4:
            field = parts[3]
            allowed = {
                "allow_player_join", "allow_reserve_queue", "allow_substitute_queue",
                "auto_silence_on_max_warning", "auto_kick_on_max_warning",
            }
            if field not in allowed:
                await callback.answer("تنظیم نامعتبر است.", show_alert=True)
                return
            setattr(settings, field, not bool(getattr(settings, field)))
        elif parts[1] == "warnings":
            settings.max_warnings = 1 if settings.max_warnings >= 5 else settings.max_warnings + 1
        await session.commit()
        await callback.message.edit_text(
            f"👥 تنظیمات بازیکنان «{group.title}»",
            reply_markup=group_player_settings_menu(group.id, settings),
        )
    await callback.answer("تنظیم ذخیره شد.")


@router.callback_query(lambda c: c.data.startswith("groupnotify:toggle:"))
async def group_notification_settings_handler(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer("درخواست اعلان نامعتبر است.", show_alert=True)
        return
    group_id, key = int(parts[2]), parts[3]
    async with session_factory() as session:
        group = await _selected_group(session, callback.bot, callback.from_user.id, group_id)
        if not group:
            await callback.answer("دسترسی گروه تأیید نشد.", show_alert=True)
            return
        settings = await _ensure_group_settings(session, group)
        try:
            values = json.loads(settings.notification_settings or "{}")
        except (TypeError, ValueError):
            values = {}
        values[key] = not bool(values.get(key, True))
        settings.notification_settings = json.dumps(values, ensure_ascii=False)
        await session.commit()
        await callback.message.edit_text(
            f"🔔 اعلان‌های «{group.title}»",
            reply_markup=group_notification_settings_menu(group.id, settings),
        )
    await callback.answer("اعلان به‌روزرسانی شد.")


@router.callback_query(lambda c: c.data.startswith("groupmgmt:locks:"))
async def legacy_group_locks(callback: CallbackQuery) -> None:
    await callback.answer("این بخش در نسخه جدید از منوی قفل گروه قابل دسترسی است.", show_alert=True)


@router.callback_query(lambda c: c.data.startswith("groupgame:active:"))
async def active_game(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    group_id = int(callback.data.rsplit(":", 1)[1])
    async with session_factory() as session:
        group = await _selected_group(session, callback.bot, callback.from_user.id, group_id)
        if not group:
            await callback.answer("دسترسی گروه تأیید نشد.", show_alert=True)
            return
        game = await GameRepository.get_active(session, group.id)
        if not game:
            await callback.message.edit_text(
                f"گروه: {group.title}\n\nدر حال حاضر بازی فعالی وجود ندارد.",
                reply_markup=group_game_menu(group.id),
            )
        else:
            scenario = await session.get(Scenario, game.scenario_id)
            await callback.message.edit_text(
                f"گروه: {group.title}\n\nبازی فعال\n"
                f"سناریو: {scenario.name_fa if scenario else 'نامشخص'}\n"
                f"وضعیت: {_status_fa(game.status)}\nمرحله: {_phase_fa(game.phase)}",
                reply_markup=active_game_menu(group.id, "menu:active_game", game.game_key, game.status == "waiting"),
            )
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("groupgame:history:"))
async def game_history(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    group_id = int(callback.data.rsplit(":", 1)[1])
    async with session_factory() as session:
        group = await _selected_group(session, callback.bot, callback.from_user.id, group_id)
        if not group:
            await callback.answer("دسترسی گروه تأیید نشد.", show_alert=True)
            return
        result = await session.execute(
            select(Game, Scenario)
            .join(Scenario, Scenario.id == Game.scenario_id)
            .where(Game.group_id == group.id)
            .order_by(desc(Game.id))
            .limit(10)
        )
        rows = list(result.all())
        if not rows:
            text = f"تاریخچه بازی‌های «{group.title}»\n\nهنوز بازی‌ای ثبت نشده است."
        else:
            lines = [f"تاریخچه بازی‌های «{group.title}»", ""]
            for game, scenario in rows:
                lines.append(
                    f"#{game.id} — {scenario.name_fa} — {_status_fa(game.status)} — {_phase_fa(game.phase)}"
                )
            text = "\n".join(lines)
        await callback.message.edit_text(text, reply_markup=group_game_menu(group.id))
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("grouplock:toggle:"))
async def toggle_group_lock(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    _, _, group_id_raw, field = callback.data.split(":", 3)
    group_id = int(group_id_raw)
    if field not in {"chat_lock", "night_lock", "turn_lock"}:
        await callback.answer("تنظیم نامعتبر است.", show_alert=True)
        return
    async with session_factory() as session:
        group = await _selected_group(session, callback.bot, callback.from_user.id, group_id)
        if not group:
            await callback.answer("دسترسی گروه تأیید نشد.", show_alert=True)
            return
        settings = (await session.execute(
            select(GroupSettings).where(GroupSettings.group_id == group.id)
        )).scalar_one_or_none()
        if settings is None:
            settings = GroupSettings(group_id=group.id)
            session.add(settings)
        setattr(settings, field, not bool(getattr(settings, field)))
        await session.commit()
        await callback.message.edit_text(
            f"قفل‌های گروه «{group.title}»",
            reply_markup=group_lock_keyboard(group.id, settings),
        )
    await callback.answer("تنظیم قفل به‌روزرسانی شد.")


@router.callback_query(lambda c: c.data.startswith("gameadmin:active:"))
async def active_game_menu_handler(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    group_id = int(callback.data.rsplit(":", 1)[1])
    async with session_factory() as session:
        group = await _selected_group(session, callback.bot, callback.from_user.id, group_id)
        if not group:
            await callback.answer("دسترسی گروه تأیید نشد.", show_alert=True)
            return
        await callback.message.edit_text(
            f"مدیریت بازی فعال\nگروه: {group.title}",
            reply_markup=active_game_menu(group.id, "menu:active_game"),
        )
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("gameadmin:info:"))
async def game_info(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    group_id = int(callback.data.rsplit(":", 1)[1])
    async with session_factory() as session:
        group = await _selected_group(session, callback.bot, callback.from_user.id, group_id)
        if not group:
            await callback.answer("دسترسی گروه تأیید نشد.", show_alert=True)
            return
        game = await GameRepository.get_active(session, group.id)
        if not game:
            await callback.message.edit_text("بازی فعالی وجود ندارد.", reply_markup=active_game_menu(group.id))
        else:
            scenario = await session.get(Scenario, game.scenario_id)
            players = await GameRepository.players(session, game.id)
            host = await session.get(User, game.host_user_id) if game.host_user_id else None
            player_lines = "\n".join(
                f"{p.seat}. {u.display_name or u.first_name}" for p, u in players
            ) or "بدون بازیکن"
            await callback.message.edit_text(
                f"اطلاعات بازی\n\n"
                f"شناسه: {game.game_key}\n"
                f"سناریو: {scenario.name_fa if scenario else 'نامشخص'}\n"
                f"وضعیت: {_status_fa(game.status)}\nمرحله: {_phase_fa(game.phase)}\n"
                f"گرداننده: {host.display_name if host else 'نامشخص'}\n\n"
                f"بازیکنان:\n{player_lines}",
                reply_markup=active_game_menu(group.id, "menu:active_game", game.game_key, game.status == "waiting"),
            )
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("gameadmin:players:"))
async def player_management(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    group_id = int(callback.data.rsplit(":", 1)[1])
    async with session_factory() as session:
        group = await _selected_group(session, callback.bot, callback.from_user.id, group_id)
        if not group:
            await callback.answer("دسترسی گروه تأیید نشد.", show_alert=True)
            return
        game = await GameRepository.get_active(session, group.id)
        if not game:
            await callback.message.edit_text("بازی فعالی وجود ندارد.", reply_markup=group_game_menu(group.id))
            return
        players = await GameRepository.players(session, game.id, include_reserve=True)
        emojis = _emoji_settings(game)
        lines = []
        for player, user in players:
            if getattr(player, "is_substitute", False):
                lines.append(f"🔁 جایگزین {player.substitute_position}. {tg_name(user.display_name or user.first_name)} — Sub")
            elif player.is_reserved:
                lines.append(f"🪑 رزرو {player.reserve_position}. {tg_name(user.display_name or user.first_name)} — رزرو")
            else:
                status = "زنده" if player.alive else {
                    "death": "کشته",
                    "kick": "کیک",
                    "slaughter": "سلاخی",
                    "faceoff": "حذف‌شده",
                }.get(player.exit_type, "حذف‌شده")
                lines.append(f"{player.seat}. {tg_name(_player_label(player, user, emojis))} — {status}")
        await callback.message.edit_text(
            "مدیریت بازیکنان\n\n" + ("\n".join(lines) if lines else "بازیکنی در بازی نیست.") +
            "\n\nعملیات موردنظر را انتخاب کنید.",
            reply_markup=player_management_menu(group.id, f"gameadmin:lobby:{game.game_key}" if callback.message.chat.type in ("group", "supergroup") else f"gameadmin:active:{group.id}"),
        )
    await callback.answer()

async def _remap_game_players_to_scenario(session, game, scenario, old_capacity: int, old_seats: dict[int, int]) -> None:
    """Preserve old seats within the new capacity; move overflow to first free seats, then reserve."""
    rows = await GameRepository.players(session, game.id, include_reserve=True)
    active = sorted(
        [row for row in rows if not row[0].is_reserved],
        key=lambda row: int(row[0].seat),
    )
    reserves = sorted(
        [row for row in rows if row[0].is_reserved],
        key=lambda row: (row[0].reserve_position is None, row[0].reserve_position or 0),
    )
    capacity = int(scenario.max_players)

    snapshot = [(player, user, int(old_seats.get(player.id, player.seat))) for player, user in active]
    preserved = [(player, user, seat) for player, user, seat in snapshot if 1 <= seat <= capacity]
    used = {seat for _, _, seat in preserved}
    remaining = [(player, user, seat) for player, user, seat in snapshot if not (1 <= seat <= capacity)]

    # Existing reserves can also fill any remaining seats before becoming reserves.
    reserve_candidates = [(player, user, 0) for player, user in reserves]
    queue = remaining + reserve_candidates
    free = [seat for seat in range(1, capacity + 1) if seat not in used]

    # Temporarily move all records away from their unique seat values.
    for index, (player, _user) in enumerate(active + reserves, 1):
        player.seat = -(index)
    await session.flush()

    for player, _user, seat in preserved:
        player.is_reserved = False
        player.reserve_position = None
        player.seat = seat

    assigned = 0
    for player, _user, _old_seat in queue:
        if assigned >= len(free):
            break
        player.is_reserved = False
        player.reserve_position = None
        player.seat = free[assigned]
        assigned += 1

    overflow = queue[assigned:]
    for player, _user, _old_seat in overflow:
        player.is_reserved = True
        player.seat = 0
        player.reserve_position = None

    # Rebuild reserve order: pre-existing reserves first, then newly overflowed players.
    reserve_rows = [player for player, _user, _old_seat in overflow]
    # Any old reserve not promoted is also still in the overflow queue if it was not assigned.
    old_reserve_ids = {int(player.id) for player, _user in reserves}
    for player, _user in reserves:
        if player.is_reserved and int(player.id) not in {int(x.id) for x in reserve_rows}:
            reserve_rows.append(player)

    # Keep the original reserve order ahead of newly overflowed active players.
    reserve_rows.sort(
        key=lambda player: (
            0 if int(player.id) in old_reserve_ids else 1,
            next((r[0].reserve_position or 0 for r in reserves if r[0].id == player.id), 0),
            int(player.id),
        )
    )
    for position, player in enumerate(reserve_rows, 1):
        player.is_reserved = True
        player.seat = 0
        player.reserve_position = position

    await session.flush()

@router.callback_query(lambda c: c.data.startswith("gameadmin:player_action:"))
async def gameadmin_player_action(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer("عملیات نامعتبر است.", show_alert=True)
        return
    group_id, action = int(parts[2]), parts[3]
    async with session_factory() as session:
        group = await _selected_group(session, callback.bot, callback.from_user.id, group_id)
        game = await GameRepository.get_active(session, group.id) if group else None
        if not group or not game:
            await callback.answer("بازی فعالی وجود ندارد.", show_alert=True)
            return
        players = await GameRepository.players(session, game.id, include_reserve=True)
        if action == "replace":
            markup = player_target_management_keyboard(group_id, action, players, only_substitute=True)
        elif action == "birthday":
            markup = player_target_management_keyboard(group_id, action, players, only_dead=True)
        else:
            markup = player_target_management_keyboard(group_id, action, players, only_alive=True)
        await callback.message.edit_text("👥 بازیکن موردنظر را انتخاب کنید:", reply_markup=markup)
    await callback.answer()

@router.callback_query(lambda c: c.data.startswith("gameadmin:player_target:"))
async def gameadmin_player_target(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    parts = callback.data.split(":")
    if len(parts) != 5:
        await callback.answer("بازیکن نامعتبر است.", show_alert=True)
        return
    group_id, action, user_id = int(parts[2]), parts[3], int(parts[4])
    async with session_factory() as session:
        group = await _selected_group(session, callback.bot, callback.from_user.id, group_id)
        game = await GameRepository.get_active(session, group.id) if group else None
        if not group or not game:
            await callback.answer("بازی فعالی وجود ندارد.", show_alert=True)
            return
        target = await session.scalar(select(GamePlayer).where(GamePlayer.game_id == game.id, GamePlayer.user_id == user_id))
        target_user = await session.get(User, user_id)
        if not target or not target_user:
            await callback.answer("بازیکن پیدا نشد.", show_alert=True)
            return
        if action == "replace":
            subs = await GameRepository.substitutes(session, game.id)
            source = next((p for p, u in subs if int(u.id) == user_id), None)
            if not source:
                await callback.answer("این بازیکن در لیست جایگزین نیست.", show_alert=True)
                return
            alive = await GameRepository.players(session, game.id)
            await callback.message.edit_text(
                f"🔁 جایگزین {tg_name(target_user.display_name or target_user.first_name)}\n\nبازیکن داخل بازی را انتخاب کنید:",
                reply_markup=player_replace_destination_keyboard(group_id, user_id, alive),
            )
            await callback.answer()
            return
        if action == "faceoff":
            destinations = [(p, u) for p, u in await GameRepository.players(session, game.id) if p.alive and not p.is_reserved and p.user_id != target.user_id]
            if not destinations:
                await callback.answer("بازیکن دیگری برای فیس‌آف وجود ندارد.", show_alert=True)
                return
            await callback.message.edit_text(
                f"🎭 فیس‌آف {tg_name(target_user.display_name or target_user.first_name)}\n\nنقش این بازیکن با کدام بازیکن تعویض شود؟",
                reply_markup=player_faceoff_destination_keyboard(group_id, user_id, destinations),
            )
            await callback.answer()
            return
        round_no = await current_round(session, game.id) if game.status == "running" else None
        if action in {"silence", "extra_turn"} and round_no is None:
            await callback.answer("این عملیات فقط در جریان دور بازی قابل اجراست.", show_alert=True)
            return
        if action == "silence":
            queue_payload = None
            if game.phase == "day":
                queue_event = await session.scalar(
                    select(GameEvent).where(
                        GameEvent.game_id == game.id,
                        GameEvent.event_type == "turn_queue",
                    ).order_by(GameEvent.id.desc())
                )
                if queue_event:
                    queue_payload = parse_turn_payload(queue_event.payload)
            silence_target_round(target, int(round_no), game.phase, queue_payload)
        elif action == "remove":
            remove_player(target, "death")
        elif action == "kick":
            apply_kick(target, target_user)
        elif action == "extra_turn":
            grant_extra_turn(target, int(round_no))
        elif action == "warning":
            target.warning_count += 1
            target_user.score -= min(target.warning_count, 5)
            settings = await _ensure_group_settings(session, group)
            if target.warning_count >= max(1, settings.max_warnings):
                if settings.auto_kick_on_max_warning:
                    target.alive, target.exit_type = False, "kick"
                elif settings.auto_silence_on_max_warning:
                    target.silence_until_round = int(round_no) + (1 if game.phase == "night" else 0)
        elif action == "birthday":
            if not restore_removed_player(target):
                await callback.answer("فقط بازیکنی که با «حذف» از بازی خارج شده می‌تواند تولد شود.", show_alert=True)
                return
        elif action == "slaughter":
            remove_player(target, "slaughter")
        else:
            await callback.answer("عملیات نامعتبر است.", show_alert=True)
            return
        await session.commit()
        if game.phase == "day":
            try:
                from app.handlers.gameplay import update_main_roster
                await update_main_roster(callback.bot, session, game)
            except Exception:
                pass
        players = await GameRepository.players(session, game.id, include_reserve=True)
        lines = []
        for p, u in players:
            if getattr(p, "is_substitute", False):
                lines.append(f"🔁 جایگزین {p.substitute_position}. {tg_name(u.display_name or u.first_name)}")
            elif p.is_reserved:
                lines.append(f"🪑 رزرو {p.reserve_position}. {tg_name(u.display_name or u.first_name)}")
            else:
                lines.append(f"{p.seat}. {tg_name(u.display_name or u.first_name)}")
        await callback.message.edit_text(
            "مدیریت بازیکنان\n\n" + ("\n".join(lines) or "بازیکنی نیست."),
            reply_markup=player_management_menu(group_id, f"gameadmin:active:{group_id}"),
        )
    await callback.answer("عملیات انجام شد.")

@router.callback_query(lambda c: c.data.startswith("gameadmin:faceoff_to:"))
async def gameadmin_faceoff_to(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    parts = callback.data.split(":")
    if len(parts) != 5:
        await callback.answer("درخواست فیس‌آف نامعتبر است.", show_alert=True)
        return
    group_id, source_id, destination_id = int(parts[2]), int(parts[3]), int(parts[4])
    if source_id == destination_id:
        await callback.answer("فیس‌آف با خود بازیکن ممکن نیست.", show_alert=True)
        return
    async with session_factory() as session:
        group = await _selected_group(session, callback.bot, callback.from_user.id, group_id)
        game = await GameRepository.get_active(session, group.id) if group else None
        if not group or not game:
            await callback.answer("بازی فعالی وجود ندارد.", show_alert=True)
            return
        source = await session.scalar(select(GamePlayer).where(GamePlayer.game_id == game.id, GamePlayer.user_id == source_id))
        destination = await session.scalar(select(GamePlayer).where(GamePlayer.game_id == game.id, GamePlayer.user_id == destination_id))
        if not source or not destination or source.is_reserved or destination.is_reserved or not source.alive or not destination.alive:
            await callback.answer("هر دو بازیکن باید زنده و داخل بازی باشند.", show_alert=True)
            return
        source_user = await session.get(User, source.user_id)
        destination_user = await session.get(User, destination.user_id)
        source_role = await session.get(Role, source.role_id) if source.role_id else None
        destination_role = await session.get(Role, destination.role_id) if destination.role_id else None
        swap_roles_for_faceoff(source, destination)
        if source_user:
            source_user.faceoffs = int(source_user.faceoffs or 0) + 1
        session.add(GameEvent(game_id=game.id, event_type="faceoff", payload=json.dumps({
            "source_user_id": source.user_id,
            "destination_user_id": destination.user_id,
            "source_role_id": source_role.id if source_role else None,
            "destination_role_id": destination_role.id if destination_role else None,
        }, ensure_ascii=False)))
        await session.commit()
        if destination_user and source_role:
            try:
                await callback.bot.send_message(
                    destination_user.telegram_id,
                    f"🎭 <b>فیس‌آف انجام شد</b>\n\nنقش جدیدت: <b>{escape(source_role.name_fa or 'بدون نقش')}</b>\n👤 نقش بازیکن فیس‌آف‌شده به تو منتقل شد.\n\n🔒 نتیجه فیس‌آف تا پایان بازی محرمانه می‌ماند.",
                    parse_mode="HTML",
                )
            except Exception:
                pass
        if game.phase == "day":
            try:
                from app.handlers.gameplay import update_main_roster
                await update_main_roster(callback.bot, session, game)
            except Exception:
                pass
        players = await GameRepository.players(session, game.id, include_reserve=True)
        lines = []
        for p, u in players:
            if p.is_substitute:
                lines.append(f"🔁 جایگزین {p.substitute_position}. {tg_name(u.display_name or u.first_name)}")
            elif p.is_reserved:
                lines.append(f"🪑 رزرو {p.reserve_position}. {tg_name(u.display_name or u.first_name)}")
            else:
                status = "زنده" if p.alive else {"death":"کشته","kick":"کیک","slaughter":"سلاخی","faceoff":"فیس‌آف"}.get(p.exit_type, "حذف‌شده")
                lines.append(f"{p.seat}. {tg_name(u.display_name or u.first_name)} — {status}")
        await callback.message.edit_text(
            "مدیریت بازیکنان\n\n" + ("\n".join(lines) or "بازیکنی نیست.") + "\n\nعملیات موردنظر را انتخاب کنید.",
            reply_markup=player_management_menu(group_id, f"gameadmin:active:{group_id}"),
        )
    await callback.answer("فیس‌آف انجام شد؛ نتیجه نقش فقط برای بازیکن مقصد ارسال شد.")

@router.callback_query(lambda c: c.data.startswith("gameadmin:player_replace_to:"))
async def gameadmin_player_replace_to(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    parts = callback.data.split(":")
    if len(parts) != 5:
        await callback.answer("درخواست جایگزینی نامعتبر است.", show_alert=True)
        return
    group_id, source_id, destination_id = int(parts[2]), int(parts[3]), int(parts[4])
    async with session_factory() as session:
        group = await _selected_group(session, callback.bot, callback.from_user.id, group_id)
        game = await GameRepository.get_active(session, group.id) if group else None
        if not group or not game:
            await callback.answer("بازی فعالی وجود ندارد.", show_alert=True)
            return
        source = await session.scalar(select(GamePlayer).where(GamePlayer.game_id == game.id, GamePlayer.user_id == source_id))
        destination = await session.scalar(select(GamePlayer).where(GamePlayer.game_id == game.id, GamePlayer.user_id == destination_id))
        if not source or not destination:
            await callback.answer("بازیکن جایگزین یا بازیکن مقصد پیدا نشد.", show_alert=True)
            return
        try:
            replaced = await GameRepository.replace_player(session, game, source, destination)
        except Exception:
            await session.rollback()
            await callback.answer("جایگزینی انجام نشد؛ وضعیت بازی تغییر نکرد.", show_alert=True)
            return
        if not replaced:
            await callback.answer("انجام جایگزینی ممکن نیست.", show_alert=True)
            return

        # Move any current-round turn references from the departed user to the
        # substitute, so replacing a speaker never leaves a stale user_id.
        current_round_no = await current_round(session, game.id) if game.status == "running" else None
        if current_round_no is not None:
            turn_events = await session.execute(
                select(GameEvent).where(
                    GameEvent.game_id == game.id,
                    GameEvent.event_type.in_(("turn_queue", "turn_state")),
                ).order_by(GameEvent.id.desc())
            )
            seen = set()
            for event in turn_events.scalars():
                if event.id in seen:
                    continue
                try:
                    data = json.loads(event.payload or "{}")
                    if int(data.get("round_no", -1)) != int(current_round_no):
                        continue
                    changed = False
                    if data.get("user_id") == destination_id:
                        data["user_id"] = source_id
                        changed = True
                    if "queue" in data:
                        new_queue = [source_id if int(uid) == destination_id else uid for uid in data.get("queue", [])]
                        if new_queue != data.get("queue", []):
                            data["queue"] = new_queue
                            changed = True
                    if changed:
                        event.payload = json.dumps(data, ensure_ascii=False)
                except (TypeError, ValueError, json.JSONDecodeError):
                    pass

        replacement_user = await session.get(User, source_id)
        replacement_role = await session.get(Role, destination.role_id) if destination.role_id else None
        await session.commit()
        if replacement_user and replacement_role:
            try:
                await callback.bot.send_message(
                    replacement_user.telegram_id,
                    f"🔁 <b>جایگزینی انجام شد</b>\n\n"
                    f"صندلی: <b>{destination.seat}</b>\n"
                    f"نقش: <b>{escape(replacement_role.name_fa or 'بدون نقش')}</b>\n\n"
                    f"شما با حفظ صندلی و نقش بازیکن مقصد وارد بازی شدی.",
                    parse_mode="HTML",
                )
            except Exception:
                pass
        if game.phase == "day":
            try:
                from app.handlers.gameplay import update_main_roster
                await update_main_roster(callback.bot, session, game)
            except Exception:
                pass
        await callback.message.edit_text(
            "✅ جایگزینی انجام شد. بازیکن قبلی از فهرست بازی خارج و جایگزین وارد بازی شد.",
            reply_markup=player_management_menu(group_id, f"gameadmin:active:{group_id}"),
        )
    await callback.answer("جایگزینی انجام شد.")

@router.callback_query(lambda c: c.data.startswith("gameadmin:scenario:"))
async def gameadmin_scenario_select(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    scenario_parts = callback.data.split(":")
    key = scenario_parts[2]
    context = scenario_parts[3] if len(scenario_parts) > 3 else "lobby"
    async with session_factory() as session:
        game = await GameRepository.get_by_key(session, key)
        if not game or game.status != "waiting":
            await callback.answer("تغییر سناریو فقط در لابی امکان‌پذیر است.", show_alert=True)
            return
        group = await _selected_group(session, callback.bot, callback.from_user.id, game.group_id)
        if not group:
            return
        scenarios = (await session.execute(
            select(Scenario).where(Scenario.enabled.is_(True), Scenario.key != "classic").order_by(Scenario.id)
        )).scalars().all()
        from app.handlers.keyboards import scenario_select_keyboard
        await callback.message.edit_text(
            "🎭 سناریوی جدید را انتخاب کنید:",
            reply_markup=scenario_select_keyboard(
                group.id, scenarios,
                back_callback=(
                    f"game:return_lobby:{game.game_key}"
                    if context == "lobby"
                    else ("groupmgmt:games" if context == "groups" else "menu:active_game")
                ),
                callback_prefix=f"gameadmin:setscenario:{game.game_key}:{context}",
            ),
        )
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("gameadmin:setscenario:"))
async def gameadmin_set_scenario(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    parts = callback.data.split(":")
    if len(parts) not in (5, 6):
        await callback.answer("درخواست تغییر سناریو نامعتبر است.", show_alert=True)
        return
    key = parts[2]
    context = parts[3] if len(parts) == 6 else "lobby"
    scenario_raw = parts[-1]
    async with session_factory() as session:
        game = await GameRepository.get_by_key(session, key)
        if not game or game.status != "waiting":
            await callback.answer("تغییر سناریو فقط در لابی امکان‌پذیر است.", show_alert=True)
            return
        group = await _selected_group(session, callback.bot, callback.from_user.id, game.group_id)
        scenario = await session.get(Scenario, int(scenario_raw))
        if not group or not scenario or not scenario.enabled or scenario.key == "classic":
            await callback.answer("سناریو قابل انتخاب نیست.", show_alert=True)
            return
        rows = await GameRepository.players(session, game.id, include_reserve=True)
        old_seats = {int(player.id): int(player.seat) for player, _user in rows if not player.is_reserved}
        old_scenario = await session.get(Scenario, game.scenario_id)
        await _remap_game_players_to_scenario(
            session, game, scenario,
            old_scenario.max_players if old_scenario else scenario.max_players,
            old_seats,
        )
        game.scenario_id = scenario.id
        await session.commit()
        await callback.answer("سناریو تغییر کرد و صندلی‌ها تطبیق داده شدند.")
        if context == "lobby":
            from app.services.game import render_lobby
            from app.handlers.keyboards import lobby_keyboard_v2
            text, full = await render_lobby(session, game)
            host = await session.get(User, game.host_user_id) if game.host_user_id else None
            await callback.message.edit_text(
                text,
                parse_mode="HTML",
                reply_markup=lobby_keyboard_v2(
                    game.game_key, scenario, await GameRepository.players(session, game.id),
                    await GameRepository.reserves(session, game.id),
                    is_host=bool(host and host.telegram_id == callback.from_user.id),
                    can_deal=full, reserve_enabled=game.reserve_enabled,
                    training_url=scenario.training_url, telegram_training_url=scenario.telegram_training_url,
                ),
            )
        else:
            back_callback = "groupmgmt:games" if context == "groups" else "menu:active_game"
            from app.handlers.keyboards import active_game_menu
            await callback.message.edit_text(
                "🎮 <b>مدیریت بازی فعال</b>\n\n"
                f"سناریو: {escape(scenario.name_fa)}\n"
                f"وضعیت: {_status_fa(game.status)}\n"
                f"مرحله: {_phase_fa(game.phase)}",
                reply_markup=active_game_menu(
                    group.id, back_callback, game.game_key, game.status == "waiting"
                ),
                parse_mode="HTML",
            )


@router.callback_query(lambda c: c.data.startswith("gameadmin:host:"))
async def gameadmin_host_select(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    host_parts = callback.data.split(":")
    key = host_parts[2]
    context = host_parts[3] if len(host_parts) > 3 else "lobby"
    async with session_factory() as session:
        game = await GameRepository.get_by_key(session, key)
        if not game or game.status != "waiting":
            await callback.answer("تغییر گرداننده فقط در لابی امکان‌پذیر است.", show_alert=True)
            return
        group = await _selected_group(session, callback.bot, callback.from_user.id, game.group_id)
        if not group:
            return
        admins = await callback.bot.get_chat_administrators(group.telegram_id)
        from app.handlers.keyboards import host_select_keyboard
        await callback.message.edit_text(
            "🎙 گرداننده جدید را انتخاب کنید:",
            reply_markup=host_select_keyboard(
                group.id, admins,
                callback_prefix=f"gameadmin:sethost:{game.game_key}:{context}",
                back_callback=(
                    f"game:return_lobby:{game.game_key}"
                    if context == "lobby"
                    else ("groupmgmt:games" if context == "groups" else "menu:active_game")
                ),
            ),
        )
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("gameadmin:sethost:"))
async def gameadmin_set_host(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    parts = callback.data.split(":")
    if len(parts) not in (5, 6):
        await callback.answer("درخواست تغییر گرداننده نامعتبر است.", show_alert=True)
        return
    key = parts[2]
    context = parts[3] if len(parts) == 6 else "lobby"
    host_raw = parts[-1]
    async with session_factory() as session:
        game = await GameRepository.get_by_key(session, key)
        if not game or game.status != "waiting":
            await callback.answer("تغییر گرداننده فقط در لابی امکان‌پذیر است.", show_alert=True)
            return
        group = await _selected_group(session, callback.bot, callback.from_user.id, game.group_id)
        if not group:
            return
        try:
            member = await callback.bot.get_chat_member(group.telegram_id, int(host_raw))
        except Exception:
            await callback.answer("اطلاعات گرداننده از تلگرام دریافت نشد.", show_alert=True)
            return
        if member.status not in ("creator", "administrator"):
            await callback.answer("گرداننده باید مدیر گروه باشد.", show_alert=True)
            return
        tg_user = member.user
        host = await UserRepository(session).upsert_from_telegram(
            tg_user.id, tg_user.username, tg_user.first_name or "", tg_user.last_name
        )
        game.host_user_id = host.id
        await session.commit()
        scenario = await session.get(Scenario, game.scenario_id)
        if context == "lobby":
            from app.services.game import render_lobby
            from app.handlers.keyboards import lobby_keyboard_v2
            text, full = await render_lobby(session, game)
            await callback.message.edit_text(
                text, parse_mode="HTML",
                reply_markup=lobby_keyboard_v2(
                    game.game_key, scenario, await GameRepository.players(session, game.id),
                    await GameRepository.reserves(session, game.id),
                    is_host=host.telegram_id == callback.from_user.id, can_deal=full,
                    reserve_enabled=game.reserve_enabled,
                    training_url=scenario.training_url if scenario else None,
                    telegram_training_url=scenario.telegram_training_url if scenario else None,
                ),
            )
        else:
            back_callback = "groupmgmt:games" if context == "groups" else "menu:active_game"
            from app.handlers.keyboards import active_game_menu
            await callback.message.edit_text(
                "🎮 <b>مدیریت بازی فعال</b>\n\n"
                f"گرداننده: {escape(host.display_name or host.first_name or 'نامشخص')}\n"
                f"سناریو: {escape(scenario.name_fa if scenario else 'نامشخص')}\n"
                f"وضعیت: {_status_fa(game.status)}\n"
                f"مرحله: {_phase_fa(game.phase)}",
                reply_markup=active_game_menu(
                    group.id, back_callback, game.game_key, game.status == "waiting"
                ),
                parse_mode="HTML",
            )
    await callback.answer("گرداننده تغییر کرد.")


@router.callback_query(lambda c: c.data.startswith("gameadmin:cancel_confirm:"))
async def cancel_game_confirm(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    group_id = int(callback.data.rsplit(":", 1)[1])
    async with session_factory() as session:
        group = await _selected_group(session, callback.bot, callback.from_user.id, group_id)
        game = await GameRepository.get_active(session, group.id) if group else None
        if not game:
            await callback.answer("بازی فعالی وجود ندارد.", show_alert=True)
            return
        if game.status not in ("draft", "waiting", "running"):
            await callback.answer("این بازی دیگر قابل لغو نیست.", show_alert=True)
            return
        game.status = "cancelled"
        game.phase = "finished"
        try:
            import app.handlers.gameplay as gameplay_module
            for task_map in (gameplay_module._challenge_tasks, gameplay_module._turn_tasks, gameplay_module._turn_live_tasks):
                task = task_map.pop(game.game_key, None)
                if task and not task.done():
                    task.cancel()
        except Exception:
            pass
        from datetime import datetime, timezone
        game.finished_at = datetime.now(timezone.utc)
        actor = await UserRepository(session).get_by_telegram_id(callback.from_user.id)
        session.add(GameEvent(
            game_id=game.id,
            actor_user_id=actor.id if actor else None,
            event_type="game_cancelled",
            payload=json.dumps({"reason": "admin_cancelled"}, ensure_ascii=False),
        ))
        await session.commit()

        # Release Telegram-side locks and remove the canonical roster before
        # destructively deleting the cancelled game.
        try:
            from app.handlers.gameplay import release_global_lock
            await release_global_lock(callback.bot, session, game)
        except Exception:
            pass
        try:
            from app.handlers.gameplay import delete_main_roster
            await delete_main_roster(callback.bot, session, game)
        except Exception:
            pass
        try:
            await release_game_number(session, game)
        except Exception:
            pass

        await GameRepository.purge(session, game.id)
        await callback.bot.send_message(
            group.telegram_id,
            "❌ بازی لغو شد و اطلاعات بازی از پایگاه داده حذف شد."
        )
        await callback.message.edit_text("بازی لغو شد و اطلاعات بازی حذف شد.", reply_markup=group_management_menu())
    await callback.answer("بازی لغو شد.")


@router.callback_query(lambda c: c.data.startswith("gameadmin:finish_result:"))
async def finish_game_result(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer("نتیجه نامعتبر است.", show_alert=True)
        return
    _, _, group_raw, winner = parts
    group_id = int(group_raw)
    async with session_factory() as session:
        group = await _selected_group(session, callback.bot, callback.from_user.id, group_id)
        game = await GameRepository.get_active(session, group.id) if group else None
        if not game or game.status != "running":
            await callback.answer("بازی در حال اجرا پیدا نشد.", show_alert=True)
            return
        labels = {"citizen": "برد شهروند", "mafia": "برد مافیا", "independent": "برد مستقل", "citizen_independent": "برد شهروند/مستقل", "draw": "مساوی"}
        await callback.message.edit_text(
            f"🏁 <b>تعیین نتیجه بازی</b>\n\nنتیجه انتخاب‌شده: <b>{labels.get(winner, winner)}</b>\n\nآیا نتیجه را تأیید می‌کنید؟",
            reply_markup=finish_game_confirm_keyboard(group.id, winner, f"day:finish_back:{game.game_key}"),
            parse_mode="HTML",
        )
    await callback.answer("نتیجه انتخاب شد؛ تأیید کنید.")


@router.callback_query(lambda c: c.data.startswith("gameadmin:finish_change:"))
async def finish_game_change_winner(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    group_id = int(callback.data.rsplit(":", 1)[1])
    async with session_factory() as session:
        group = await _selected_group(session, callback.bot, callback.from_user.id, group_id)
        game = await GameRepository.get_active(session, group.id) if group else None
        if not game or game.status != "running":
            await callback.answer("بازی در حال اجرا پیدا نشد.", show_alert=True)
            return
        await callback.message.edit_text(
            "🏁 <b>تعیین برنده بازی</b>\n\nتیم برنده را انتخاب کنید:",
            reply_markup=__import__("app.handlers.keyboards", fromlist=["finish_game_keyboard"]).finish_game_keyboard(
                group.id, f"day:finish_back:{game.game_key}"
            ),
            parse_mode="HTML",
        )
    await callback.answer("انتخاب برنده را دوباره انجام بده.")


@router.callback_query(lambda c: c.data.startswith("gameadmin:finish_confirm:"))
async def finish_game_confirm(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer("نتیجه نامعتبر است.", show_alert=True)
        return
    _, _, group_raw, winner = parts
    group_id = int(group_raw)
    async with session_factory() as session:
        group = await _selected_group(session, callback.bot, callback.from_user.id, group_id)
        game = await GameRepository.get_active(session, group.id) if group else None
        if not game or game.status != "running":
            await callback.answer("بازی در حال اجرا پیدا نشد.", show_alert=True)
            return
        from app.services.gameplay import finalize_game
        try:
            await finalize_game(session, game, winner)
            await session.commit()
            from app.handlers.gameplay import delete_main_roster, release_global_lock
            await release_global_lock(callback.bot, session, game)
            await delete_main_roster(callback.bot, session, game)
        except ValueError as exc:
            await callback.answer(str(exc), show_alert=True)
            return
        # The game belongs to the selected group, not to the private
        # management chat where the host pressed the button.
        group_chat_id = int(group.telegram_id)
        result_html = await _game_result_rich_html(session, game, winner)
        fallback_html = (
            "🏁 <b>نتیجه نهایی بازی</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            + (await _game_result_text(session, game, winner))
        )
        try:
            try:
                await send_rich_message(callback.bot, group_chat_id, result_html, is_rtl=True)
            except Exception:
                # Rich Message failure must never block the game result.
                await callback.bot.send_message(
                    group_chat_id,
                    fallback_html,
                    parse_mode="HTML",
                    reply_markup=game_result_keyboard(group.id, game.id),
                )
            await callback.message.edit_text("✅ نتیجه بازی ثبت شد و گزارش نهایی در گروه ارسال شد.")
        except Exception:
            await callback.message.edit_text("⚠️ نتیجه بازی ثبت شد، اما ارسال گزارش نهایی به گروه ناموفق بود.")
    await callback.answer("نتیجه بازی ثبت شد.")




@router.callback_query(lambda c: c.data.startswith("gameadmin:number:"))
async def gameadmin_number(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.message or not callback.from_user:
        return
    group_id = int(callback.data.rsplit(":", 1)[1])
    async with session_factory() as session:
        group = await _selected_group(session, callback.bot, callback.from_user.id, group_id)
        game = await GameRepository.get_active(session, group.id) if group else None
        if not game:
            await callback.answer("بازی فعالی وجود ندارد.", show_alert=True)
            return
        current = await get_game_number(session, game)
    await state.set_state(GameEventState.game_number)
    await state.update_data(game_id=game.id)
    await callback.message.answer(
        f"🔢 شماره فعلی بازی: <b>{current}</b>\n\nشماره جدید را به‌صورت عدد صحیح ارسال کنید:",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(GameEventState.game_number)
async def gameadmin_number_text(message: Message, state: FSMContext) -> None:
    if not message.from_user or not message.text:
        return
    raw = message.text.strip()
    try:
        number = int(raw)
    except ValueError:
        await message.answer("شماره بازی باید یک عدد صحیح مثبت باشد.")
        return
    if number < 1:
        await message.answer("شماره بازی باید بزرگ‌تر از صفر باشد.")
        return
    data = await state.get_data()
    game_id = data.get("game_id")
    async with session_factory() as session:
        game = await session.get(Game, int(game_id)) if game_id else None
        actor = await UserRepository(session).get_by_telegram_id(message.from_user.id)
        group = await session.get(Group, game.group_id) if game else None
        allowed = bool(game and actor and group and await _can_manage_game_events(session, message.bot, game, actor, group))
        if not allowed or game.status not in {"waiting", "running"}:
            await state.clear()
            await message.answer("بازی فعال یا دسترسی لازم وجود ندارد.")
            return
        try:
            await set_game_number(session, game, number)
        except ValueError as exc:
            await message.answer(str(exc))
            return
    await state.clear()
    await message.answer(f"✅ شماره بازی به <b>{number}</b> تغییر کرد.", parse_mode="HTML")
    # Refresh the canonical public roster so the new number is visible immediately.
    try:
        from app.handlers.gameplay import update_main_roster
        async with session_factory() as session:
            game = await session.get(Game, int(game_id))
            if game:
                await update_main_roster(message.bot, session, game)
    except Exception:
        pass


@router.callback_query(lambda c: c.data.startswith("gameadmin:event_game:"))
async def game_event_select(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    game_id = int(callback.data.rsplit(":", 1)[1])
    async with session_factory() as session:
        game = await session.get(Game, game_id)
        actor = await UserRepository(session).get_by_telegram_id(callback.from_user.id)
        group = await session.get(Group, game.group_id) if game else None
        allowed = bool(game and actor and group and await _can_manage_game_events(session, callback.bot, game, actor, group))
        if not allowed:
            await callback.answer("مدیرِ بازیکنِ این بازی اجازه مشاهده یا ثبت اتفاقات مخفی را ندارد.", show_alert=True)
            return
        await callback.message.edit_text(
            "📜 <b>مدیریت اتفاقات بازی</b>\n\nاتفاقات فقط برای همین بازی ثبت می‌شوند.",
            reply_markup=game_event_management_keyboard(game.id, game.group_id),
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("gameadmin:event_add:"))
async def game_event_add(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.message or not callback.from_user:
        return
    game_id = int(callback.data.rsplit(":", 1)[1])
    async with session_factory() as session:
        game = await session.get(Game, game_id)
        actor = await UserRepository(session).get_by_telegram_id(callback.from_user.id)
        group = await session.get(Group, game.group_id) if game else None
        allowed = bool(game and actor and group and await _can_manage_game_events(session, callback.bot, game, actor, group))
        if not allowed:
            await callback.answer("مدیرِ بازیکنِ این بازی اجازه ثبت اتفاقات مخفی را ندارد.", show_alert=True)
            return
        if game.auto_play:
            await callback.answer("ثبت دستی اتفاقات فقط برای بازی غیرخودکار فعال است.", show_alert=True)
            return
    await state.set_state(GameEventState.description)
    await state.update_data(game_id=game_id)
    await callback.message.answer("متن اتفاق بازی را ارسال کنید:")
    await callback.answer()


@router.message(GameEventState.description)
async def game_event_add_text(message: Message, state: FSMContext) -> None:
    if not message.from_user or not message.text:
        return
    data = await state.get_data()
    game_id = data.get("game_id")
    async with session_factory() as session:
        game = await session.get(Game, int(game_id)) if game_id else None
        actor = await UserRepository(session).get_by_telegram_id(message.from_user.id)
        group = await session.get(Group, game.group_id) if game else None
        allowed = bool(game and actor and group and await _can_manage_game_events(session, message.bot, game, actor, group))
        if not allowed or game.auto_play:
            await state.clear()
            await message.answer("بازی فعال یا دسترسی لازم وجود ندارد.")
            return
        await _event(
            session,
            game,
            "manual_game_event",
            {"round_no": await current_round(session, game.id), "text": message.text.strip()},
            actor.id,
        )
        await session.commit()
    await state.clear()
    await message.answer("اتفاق بازی ثبت شد.")


async def _game_roles_text(session, game) -> str:
    rows = list((await session.execute(
        select(GamePlayer, User, Role)
        .outerjoin(Role, Role.id == GamePlayer.role_id)
        .join(User, User.id == GamePlayer.user_id)
        .where(GamePlayer.game_id == game.id)
        .order_by(GamePlayer.seat)
    )).all())
    try:
        emoji_settings = json.loads(game.emoji_settings or "{}")
    except (TypeError, ValueError):
        emoji_settings = {}
    winner_event = await session.scalar(select(GameEvent).where(
        GameEvent.game_id == game.id,
        GameEvent.event_type.in_(["game_finished", "stats_recorded"])
    ).order_by(GameEvent.id.desc()))
    winner = (json.loads(winner_event.payload or "{}").get("winner") if winner_event else "draw")
    body = []
    for player, user, role in rows:
        if player.is_reserved:
            continue
        name = tg_mention(user.telegram_id, user.display_name or user.first_name or user.username or "بازیکن")
        role_name = escape(role.name_fa if role else "بدون نقش")
        team = {"mafia": "مافیا", "citizen": "شهروند", "independent": "مستقل"}.get(role.team if role else "", "نامشخص")
        badges = []
        if ((winner == "mafia" and role and role.team == "mafia") or
            (winner == "citizen" and role and role.team == "citizen") or
            (winner == "independent" and role and role.team == "independent") or
            (winner == "citizen_independent" and role and role.team in {"citizen", "independent"})):
            badges.append("🏆")
        if not player.alive:
            badges.append("☠️")
            if player.exit_type == "kick" and emoji_settings.get("kick", True):
                badges.append("⛔")
            elif player.exit_type == "slaughter" and emoji_settings.get("slaughter", True):
                badges.append("🔪")
            elif player.exit_type == "vote":
                badges.append("🗳")
            elif player.exit_type == "faceoff":
                badges.append("🎭")
        if player.warning_count and emoji_settings.get("warning", True):
            badges.append(f"⚠️{player.warning_count}")
        badge_text = " ".join(dict.fromkeys(badges))
        body.append(
            f"<tr><td align=\"center\">{int(player.seat)}</td>"
            f"<td>{name}</td><td><b>{role_name}</b></td>"
            f"<td>{escape(team)}</td><td>{escape(badge_text or '—')}</td></tr>"
        )
    table = (
        '<table bordered striped compact>'
        '<tr><th>#</th><th>بازیکن</th><th>نقش</th><th>ساید</th><th>وضعیت</th></tr>'
        + "".join(body) +
        '</table>'
    ) if body else '<p>بازیکنی برای نمایش وجود ندارد.</p>'
    return "<h2>🎭 لیست بازیکنان و نقش‌ها</h2>" + table

async def _game_ranking_text(session, game) -> str:
    rows = list((await session.execute(
        select(User)
        .join(GamePlayer, GamePlayer.user_id == User.id)
        .join(Game, Game.id == GamePlayer.game_id)
        .where(
            Game.group_id == game.group_id,
            User.is_active.is_(True),
            User.games_played > 0,
        )
        .distinct()
        .order_by(User.score.desc(), User.games_won.desc(), User.games_played.desc())
        .limit(10)
    )).scalars().all())
    if not rows:
        return "<h2>🏆 رتبه‌بندی بازیکنان</h2><p>هنوز بازی کاملی برای رتبه‌بندی ثبت نشده است.</p>"
    body = []
    for i, user in enumerate(rows, 1):
        body.append(
            f"<tr><td align=\"center\">{i}</td>"
            f"<td>{tg_mention(user.telegram_id, user.display_name or user.first_name or 'بازیکن')}</td>"
            f"<td align=\"center\">{int(user.score)}</td>"
            f"<td>{escape(rank_for_score(user.score))}</td></tr>"
        )
    return (
        "<h2>🏆 رتبه‌بندی بازیکنان</h2>"
        '<table bordered striped compact>'
        '<tr><th>جایگاه</th><th>بازیکن</th><th>امتیاز</th><th>رتبه</th></tr>'
        + "".join(body) +
        "</table>"
    )

async def _game_result_rich_html(session, game, winner: str) -> str:
    """Default result view; roles/ranking are opened from Rich Message buttons."""
    result_text = await _game_result_text(session, game, winner)

    def panel(value: str) -> str:
        return value.replace("\n", "<br/>")

    return (
        '<h2>🏁 نتیجه نهایی بازی</h2>'
        f'<section><table bordered striped compact>'
        '<tr><th>🏁 نتیجه بازی</th></tr>'
        f'<tr><td>{panel(result_text)}</td></tr>'
        '</table></section>'
        '<p><tg-button-row align="center">'
        f'<tg-button type="callback_data" style="primary" data="gameresult:view:ranking:{game.id}">🏆 رتبه‌بندی</tg-button>'
        f'<tg-button type="callback_data" style="success" data="gameresult:view:roles:{game.id}">🎭 نقش‌ها</tg-button>'
        f'<tg-button type="callback_data" style="primary" data="gameresult:view:result:{game.id}">🏁 نتیجه بازی</tg-button>'
        f'<tg-button type="callback_data" style="link" data="gameresult:private:{game.id}">📩 نمایش نتیجه برای من</tg-button>'
        '</tg-button-row></p>'
    )


async def _result_payload(session, game, view: str) -> tuple[str, str]:
    winner_event = await session.scalar(select(GameEvent).where(
        GameEvent.game_id == game.id,
        GameEvent.event_type.in_(["game_finished", "stats_recorded"]),
    ).order_by(GameEvent.id.desc()))
    winner = (json.loads(winner_event.payload or "{}").get("winner") if winner_event else "draw")
    if view == "roles":
        text = await _game_roles_text(session, game)
        title = "🎭 لیست بازیکنان و نقش‌ها"
    elif view == "ranking":
        text = await _game_ranking_text(session, game)
        title = "🏆 رتبه‌بندی کلی گروه"
    else:
        text = (
            "🏁 <b>نتیجه نهایی بازی</b>\n"
            "گزارش کامل بازی و وضعیت بازیکنان:\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            + (await _game_result_text(session, game, winner))
        )
        title = "🏁 نتیجه بازی"
    return title, text


def _result_rich_view(game_id: int, title: str, text: str) -> str:
    rich_body = text if title != "🏁 نتیجه بازی" else text.replace("\n", "<br/>")
    return (
        f"<h2>{title}</h2>{rich_body}"
        '<p><tg-button-row align="center">'
        f'<tg-button type="callback_data" style="primary" data="gameresult:view:ranking:{game_id}">🏆 رتبه‌بندی</tg-button>'
        f'<tg-button type="callback_data" style="success" data="gameresult:view:roles:{game_id}">🎭 نقش‌ها</tg-button>'
        f'<tg-button type="callback_data" style="primary" data="gameresult:view:result:{game_id}">🏁 نتیجه بازی</tg-button>'
        '</tg-button-row></p>'
    )


async def _result_group_access(callback: CallbackQuery, session, game) -> tuple[bool, str]:
    if callback.message.chat.type not in ("group", "supergroup"):
        return True, ""
    group = await session.get(Group, game.group_id)
    actor = await UserRepository(session).get_by_telegram_id(callback.from_user.id)
    if not group or not actor:
        return False, "دسترسی به نتیجه بازی تأیید نشد."
    if game.host_user_id == actor.id or await _is_group_admin(callback.bot, group, actor.telegram_id):
        return True, ""
    return False, "تب‌های نتیجه در گروه فقط برای گرداننده و مدیران گروه فعال است. برای مشاهده نتیجه شخصی، «📩 نمایش نتیجه برای من» را بزنید."


async def _apply_result_group_cooldown(session, game) -> tuple[bool, int]:
    settings = await session.scalar(select(GroupSettings).where(GroupSettings.group_id == game.group_id).with_for_update())
    if settings is None:
        settings = GroupSettings(group_id=game.group_id)
        session.add(settings)
        await session.flush()
    now = datetime.now(timezone.utc)
    cooldown = max(0, int(settings.result_tab_cooldown_seconds or 10))
    last = settings.result_tab_last_changed_at
    if last is not None:
        elapsed = (now - last).total_seconds()
        remaining = cooldown - int(elapsed)
        if remaining > 0:
            return False, remaining
    settings.result_tab_last_changed_at = now
    return True, 0


@router.callback_query(lambda c: c.data.startswith("gameresult:private:"))
async def game_result_private(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    game_id = int(callback.data.rsplit(":", 1)[1])
    if callback.message.chat.type not in ("group", "supergroup"):
        await callback.answer("این دکمه فقط از پیام نتیجه گروه استفاده می‌شود.", show_alert=True)
        return
    async with session_factory() as session:
        game = await session.get(Game, game_id)
        if not game or game.status != "finished":
            await callback.answer("نتیجه این بازی در دسترس نیست.", show_alert=True)
            return
        user = await UserRepository(session).get_by_telegram_id(callback.from_user.id)
        if not user:
            await callback.answer("حساب شما هنوز ثبت نشده است.", show_alert=True)
            return
        title, text = await _result_payload(session, game, "result")
        rich = _result_rich_view(game.id, title, text)
        viewer = await session.scalar(select(GameResultViewer).where(
            GameResultViewer.game_id == game.id,
            GameResultViewer.user_id == user.id,
        ))
        if viewer and viewer.chat_id == callback.from_user.id:
            try:
                await edit_rich_message(callback.bot, viewer.chat_id, viewer.message_id, rich, is_rtl=True)
            except Exception:
                sent = await send_rich_message(callback.bot, callback.from_user.id, rich, is_rtl=True)
                viewer.message_id = sent.message_id
        else:
            sent = await send_rich_message(callback.bot, callback.from_user.id, rich, is_rtl=True)
            if viewer:
                viewer.chat_id = callback.from_user.id
                viewer.message_id = sent.message_id
                viewer.current_view = "result"
            else:
                session.add(GameResultViewer(
                    game_id=game.id,
                    user_id=user.id,
                    chat_id=callback.from_user.id,
                    message_id=sent.message_id,
                    current_view="result",
                ))
        await session.commit()
    await callback.answer("نتیجه در پیام خصوصی شما باز شد.")


@router.callback_query(lambda c: c.data.startswith("gameresult:view:"))
async def game_result_view(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer("نمایش نتیجه نامعتبر است.", show_alert=True)
        return
    _, _, view, game_raw = parts
    game_id = int(game_raw)
    if view not in {"result", "roles", "ranking"}:
        await callback.answer("تب نتیجه نامعتبر است.", show_alert=True)
        return
    async with session_factory() as session:
        game = await session.get(Game, game_id)
        if not game:
            await callback.answer("بازی پیدا نشد.", show_alert=True)
            return
        allowed, reason = await _result_group_access(callback, session, game)
        if not allowed:
            await callback.answer(reason, show_alert=True)
            return
        if callback.message.chat.type in ("group", "supergroup"):
            ok, remaining = await _apply_result_group_cooldown(session, game)
            if not ok:
                await session.rollback()
                await callback.answer(f"⏳ برای تغییر تب {remaining} ثانیه صبر کنید.", show_alert=False)
                return
        title, text = await _result_payload(session, game, view)
        rich_view = _result_rich_view(game.id, title, text)
        if callback.message.chat.type in ("group", "supergroup"):
            try:
                await edit_rich_message(
                    callback.bot, callback.message.chat.id, callback.message.message_id,
                    rich_view, is_rtl=True,
                )
            except Exception:
                await callback.message.edit_text(
                    text,
                    reply_markup=game_result_keyboard(game.group_id, game.id),
                    parse_mode="HTML",
                )
        else:
            user = await UserRepository(session).get_by_telegram_id(callback.from_user.id)
            viewer = await session.scalar(select(GameResultViewer).where(
                GameResultViewer.game_id == game.id,
                GameResultViewer.user_id == user.id if user else False,
            ))
            if not viewer or viewer.message_id != callback.message.message_id:
                await callback.answer("این پیام نتیجه دیگر معتبر نیست.", show_alert=True)
                await session.rollback()
                return
            viewer.current_view = view
            try:
                await edit_rich_message(
                    callback.bot, callback.message.chat.id, callback.message.message_id,
                    rich_view, is_rtl=True,
                )
            except Exception:
                await callback.message.edit_text(text, parse_mode="HTML")
        await session.commit()
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("gameresult:back:"))
async def game_result_back(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    game_id = int(callback.data.rsplit(":", 1)[1])
    async with session_factory() as session:
        game = await session.get(Game, game_id)
        if not game:
            await callback.answer("بازی پیدا نشد.", show_alert=True)
            return
        allowed, reason = await _result_group_access(callback, session, game)
        if not allowed:
            await callback.answer(reason, show_alert=True)
            return
        if callback.message.chat.type in ("group", "supergroup"):
            ok, remaining = await _apply_result_group_cooldown(session, game)
            if not ok:
                await session.rollback()
                await callback.answer(f"⏳ برای تغییر تب {remaining} ثانیه صبر کنید.")
                return
        title, text = await _result_payload(session, game, "result")
        rich = _result_rich_view(game.id, title, text)
        try:
            await edit_rich_message(
                callback.bot, callback.message.chat.id, callback.message.message_id,
                rich, is_rtl=True,
            )
        except Exception:
            await callback.message.edit_text(
                text,
                reply_markup=game_result_keyboard(game.group_id, game.id),
                parse_mode="HTML",
            )
        await session.commit()
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("gameresult:register:"))
async def game_result_register(callback: CallbackQuery) -> None:
    game_id = int(callback.data.rsplit(":", 1)[1])
    async with session_factory() as session:
        game = await session.get(Game, game_id)
        if not game or not callback.from_user:
            await callback.answer("بازی پیدا نشد.", show_alert=True)
            return
        actor = await UserRepository(session).get_by_telegram_id(callback.from_user.id)
        group = await session.get(Group, game.group_id)
        if not actor or not group or not (
            game.host_user_id == actor.id or await _is_group_admin(callback.bot, group, actor.telegram_id)
        ):
            await callback.answer("فقط گرداننده یا مدیر گروه می‌تواند بازی را ثبت کند.", show_alert=True)
            return
        exists = await session.scalar(select(GameEvent.id).where(
            GameEvent.game_id == game.id, GameEvent.event_type == "game_registered"
        ))
        if not exists:
            session.add(GameEvent(
                game_id=game.id,
                actor_user_id=(await UserRepository(session).get_by_telegram_id(callback.from_user.id)).id if callback.from_user else None,
                event_type="game_registered",
                payload=json.dumps({"registered": True}, ensure_ascii=False),
            ))
            await session.commit()
        await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer("بازی ثبت شد.")


@router.callback_query(lambda c: c.data.startswith("gameresult:history:"))
async def game_result_history(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    game_id = int(callback.data.rsplit(":", 1)[1])
    async with session_factory() as session:
        game = await session.get(Game, game_id)
        if not game:
            await callback.answer("بازی پیدا نشد.", show_alert=True)
            return
        result = await session.execute(
            select(Game, Scenario).join(Scenario, Scenario.id == Game.scenario_id)
            .where(Game.group_id == game.group_id).order_by(desc(Game.id)).limit(10)
        )
        rows = list(result.all())
        lines = ["📚 <b>تاریخچه بازی‌ها</b>", ""]
        for item, scenario in rows:
            lines.append(f"#{item.id} — {escape(scenario.name_fa)} — {item.status}")
        await callback.message.edit_text("\n".join(lines), reply_markup=game_result_back_keyboard(game.id), parse_mode="HTML")
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("gameresult:ranking:"))
async def game_result_ranking(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    game_id = int(callback.data.rsplit(":", 1)[1])
    async with session_factory() as session:
        game = await session.get(Game, game_id)
        if not game:
            await callback.answer("بازی پیدا نشد.", show_alert=True)
            return
        rows = await leaderboard(session, 10)
        lines = ["🏆 <b>رتبه‌بندی بازیکنان</b>", ""]
        if not rows:
            lines.append("هنوز بازی کاملی برای رتبه‌بندی ثبت نشده است.")
        else:
            for i, user in enumerate(rows, 1):
                lines.append(f"{i}. {tg_name(user.display_name or user.first_name or 'بازیکن')} — {user.score} امتیاز — {rank_for_score(user.score)}")
        await callback.message.edit_text("\n".join(lines), reply_markup=game_result_back_keyboard(game.id), parse_mode="HTML")
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("gameresult:stats:"))
async def game_result_stats(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    game_id = int(callback.data.rsplit(":", 1)[1])
    async with session_factory() as session:
        game = await session.get(Game, game_id)
        if not game:
            await callback.answer("بازی پیدا نشد.", show_alert=True)
            return
        await callback.message.edit_text(
            "📊 <b>آمار بازی</b>",
            reply_markup=game_result_back_keyboard(game.id),
            parse_mode="HTML",
        )
    await callback.answer()
@router.callback_query(lambda c: c.data.startswith("gameresult:events:"))
async def game_result_events(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    game_id = int(callback.data.rsplit(":", 1)[1])
    async with session_factory() as session:
        game = await session.get(Game, game_id)
        if not game:
            await callback.answer("بازی پیدا نشد.", show_alert=True)
            return
        if game.status != "finished" or not await _is_finished_game_player(session, game.id, callback.from_user.id):
            await callback.answer("اتفاقات مخفی فقط پس از پایان بازی و فقط برای بازیکنان اصلی همان بازی قابل مشاهده است.", show_alert=True)
            return
        group = await session.get(Group, game.group_id)
        if not group:
            await callback.answer("گروه بازی پیدا نشد.", show_alert=True)
            return
        # Only curated gameplay events are exposed; internal state-machine
        # events such as turn_state, challenge_request and vote_state are hidden.
        result = await session.execute(select(GameEvent).where(
            GameEvent.game_id == game.id,
            GameEvent.event_type.in_(["night_action", "night_resolved", "manual_game_event"]),
        ).order_by(GameEvent.id.asc()))
        events = list(result.scalars())
        by_round: dict[int, dict] = {}
        for event in events:
            data = json.loads(event.payload or "{}")
            round_no = int(data.get("round_no", 1) or 1)
            by_round.setdefault(round_no, {"actions": [], "manual": []})
            if event.event_type == "night_action":
                by_round[round_no]["actions"].append((event, data))
            elif event.event_type == "manual_game_event":
                by_round[round_no]["manual"].append((event, data))
        # Send one chronological message per round into the group.
        for round_no in sorted(by_round):
            groups = {"مافیا": [], "شهروند": [], "مستقل": [], "سایر": []}
            for event, data in by_round[round_no]["actions"]:
                actor = await session.get(User, event.actor_user_id) if event.actor_user_id else None
                role = await session.scalar(select(Role).join(GamePlayer, GamePlayer.role_id == Role.id).where(
                    GamePlayer.game_id == game.id, GamePlayer.user_id == event.actor_user_id
                )) if event.actor_user_id else None
                target = await session.get(User, int(data["target_user_id"])) if data.get("target_user_id") else None
                target_name = target.display_name or target.first_name or "بازیکن" if target else "بازیکن"
                labels = {
                    "mafia_kill": "شات شب",
                    "doctor_save": "دکتر",
                    "detective_check": "کاراگاه",
                }
                label = labels.get(data.get("action_type"), data.get("action_type", "اقدام شب"))
                team_label = "مافیا" if role and role.team == "mafia" else "شهروند" if role and role.team == "citizen" else "مستقل" if role and role.team == "independent" else "سایر"
                groups[team_label].append(f"{label}: {escape(target_name)}")
            for _event, data in by_round[round_no]["manual"]:
                groups["سایر"].append(escape(str(data.get("text", ""))))
            title = "🌙 شب معارفه" if round_no == 1 else f"🌙 شب {round_no}"
            lines = [f"<b>{title}</b>", ""]
            for team_label in ("مافیا", "شهروند", "مستقل", "سایر"):
                if groups[team_label]:
                    lines.append(f"<b>{team_label}:</b>")
                    lines.extend(f"• {item}" for item in groups[team_label])
                    lines.append("")
            if len(lines) > 2:
                await callback.bot.send_message(group.telegram_id, "\n".join(lines).strip(), parse_mode="HTML")
        await callback.answer("اتفاقات بازی به ترتیب ثبت در گروه ارسال شد.")
    await callback.answer()
@router.callback_query(lambda c: c.data.startswith("gameadmin:emoji:"))
async def emoji_management(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    group_id = int(callback.data.rsplit(":", 1)[1])
    async with session_factory() as session:
        group = await _selected_group(session, callback.bot, callback.from_user.id, group_id)
        game = await GameRepository.get_active(session, group.id) if group else None
        if not game:
            await callback.answer("بازی فعالی وجود ندارد.", show_alert=True)
            return
        from app.handlers.keyboards import emoji_management_menu
        await callback.message.edit_text("مدیریت اموجی‌های وضعیت بازیکنان و بازی", reply_markup=emoji_management_menu(group.id, _emoji_settings(game)))
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("gameadmin:emoji_toggle:"))
async def emoji_toggle(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer("تنظیم اموجی نامعتبر است.", show_alert=True)
        return
    _, _, group_raw, key = parts
    group_id = int(group_raw)
    async with session_factory() as session:
        group = await _selected_group(session, callback.bot, callback.from_user.id, group_id)
        game = await GameRepository.get_active(session, group.id) if group else None
        if not game:
            await callback.answer("بازی فعالی وجود ندارد.", show_alert=True)
            return
        settings = _emoji_settings(game)
        if key not in settings:
            await callback.answer("اموجی نامعتبر است.", show_alert=True)
            return
        settings[key] = not settings[key]
        game.emoji_settings = json.dumps(settings, ensure_ascii=False)
        await session.commit()
        from app.handlers.keyboards import emoji_management_menu
        await callback.message.edit_text("مدیریت اموجی‌های وضعیت بازیکنان و بازی", reply_markup=emoji_management_menu(group.id, settings))
    await callback.answer("تنظیم اموجی ذخیره شد.")


@router.callback_query(lambda c: c.data.startswith("gameadmin:features:"))
async def game_features_menu_handler(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    group_id = int(callback.data.rsplit(":", 1)[1])
    async with session_factory() as session:
        group = await _selected_group(session, callback.bot, callback.from_user.id, group_id)
        if not group:
            return
        game = await GameRepository.get_active(session, group.id)
        if not game:
            await callback.answer("بازی فعالی وجود ندارد.", show_alert=True)
            return
        await callback.message.edit_text(
            "⚙️ <b>تنظیمات بازی</b>",
            reply_markup=game_features_menu(
                group.id,
                game.challenge_enabled,
                game.challenge_mode,
                game.next_host_enabled,
                game.next_player_enabled,
                game.next_auto_enabled,
                game.auto_silence_warnings,
                game.auto_kick_warnings,
                game.turn_seconds,
                game.challenge_seconds,
                game.extra_challenge_seconds,
                back_callback=f"game:return_lobby:{game.game_key}" if game.status == "waiting" else f"gameadmin:active:{group.id}",
                game_key=game.game_key,
            ),
            parse_mode="HTML",
        )
    await callback.answer()

@router.callback_query(lambda c: c.data.startswith("gameadmin:feature:"))
async def game_feature_handler(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer("تنظیم بازی نامعتبر است.", show_alert=True)
        return
    _, _, group_raw, action = parts
    group_id = int(group_raw)
    async with session_factory() as session:
        group = await _selected_group(session, callback.bot, callback.from_user.id, group_id)
        game = await GameRepository.get_active(session, group.id) if group else None
        if not game:
            await callback.answer("بازی فعالی وجود ندارد.", show_alert=True)
            return
        if action == "cancel":
            await callback.message.edit_text("آیا از لغو واقعی بازی مطمئن هستید؟", reply_markup=__import__("app.handlers.keyboards", fromlist=["cancel_game_keyboard"]).cancel_game_keyboard(group.id))
            await callback.answer()
            return
        if action == "events":
            actor = await UserRepository(session).get_by_telegram_id(callback.from_user.id)
            if not actor or not await _can_manage_game_events(session, callback.bot, game, actor, group):
                await callback.answer("فقط گرداننده یا مدیر مجاز بازی می‌تواند اتفاقات آن را مدیریت کند.", show_alert=True)
                return
            await callback.message.edit_text(
                "📜 <b>اتفاقات بازی</b>\n\nاتفاقات ثبت‌شده برای همین بازی را مدیریت کنید.",
                reply_markup=game_event_management_keyboard(game.id, game.group_id),
                parse_mode="HTML",
            )
            await callback.answer()
            return
        if action == "finish":
            await callback.message.edit_text("نتیجه نهایی را انتخاب کنید:", reply_markup=__import__("app.handlers.keyboards", fromlist=["finish_game_keyboard"]).finish_game_keyboard(group.id))
            await callback.answer()
            return
        if action == "challenge":
            if not game.challenge_enabled:
                game.challenge_enabled = True
                game.challenge_mode = "limited"
            elif game.challenge_mode == "limited":
                game.challenge_mode = "free"
            else:
                game.challenge_enabled = False
        elif action == "next_host":
            game.next_host_enabled = not game.next_host_enabled
        elif action == "next_player":
            game.next_player_enabled = not game.next_player_enabled
        elif action == "next_auto":
            game.next_auto_enabled = not game.next_auto_enabled
        elif action == "auto_silence":
            game.auto_silence_warnings = not game.auto_silence_warnings
        elif action == "auto_kick":
            game.auto_kick_warnings = not game.auto_kick_warnings
        else:
            await callback.answer("تنظیم نامعتبر است.", show_alert=True)
            return
        await session.commit()
        await callback.message.edit_text(
            "تنظیمات بازی",
            reply_markup=game_features_menu(
                group.id, game.challenge_enabled, game.challenge_mode, game.next_host_enabled, game.next_player_enabled,
                game.next_auto_enabled, game.auto_silence_warnings, game.auto_kick_warnings,
                game.turn_seconds, game.challenge_seconds, game.extra_challenge_seconds,
                back_callback=f"game:return_lobby:{game.game_key}" if game.status == "waiting" else f"gameadmin:active:{group.id}",
                game_key=game.game_key,
            ),
        )
    await callback.answer("تنظیم ذخیره شد.")

@router.callback_query(lambda c: c.data.startswith("gameadmin:time:"))
async def game_time_menu(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer("تنظیم زمان نامعتبر است.", show_alert=True)
        return
    _, _, group_raw, kind = parts
    group_id = int(group_raw)
    async with session_factory() as session:
        group = await _selected_group(session, callback.bot, callback.from_user.id, group_id)
        game = await GameRepository.get_active(session, group.id) if group else None
        if not game:
            await callback.answer("بازی فعالی وجود ندارد.", show_alert=True)
            return
        current = {
            "turn": game.turn_seconds,
            "challenge": game.challenge_seconds,
            "extra_challenge": game.extra_challenge_seconds,
        }.get(kind)
        if current is None:
            await callback.answer("نوع زمان نامعتبر است.", show_alert=True)
            return
        from app.handlers.keyboards import duration_keyboard
        await callback.message.edit_text(
            "انتخاب زمان " + {"turn": "نوبت", "challenge": "چالش", "extra_challenge": "چالش اضافه"}[kind],
            reply_markup=duration_keyboard(
                "gameadmin", group.id, kind, current,
                f"gameadmin:features:{group.id}",
            ),
        )
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("gameadmin:set_time:"))
async def game_set_time(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    if len(parts) != 5:
        await callback.answer("تنظیم زمان نامعتبر است.", show_alert=True)
        return
    _, _, group_raw, kind, value_raw = parts
    group_id, value = int(group_raw), int(value_raw)
    if kind not in {"turn", "challenge", "extra_challenge"} or not 15 <= value <= 600:
        await callback.answer("مقدار زمان نامعتبر است.", show_alert=True)
        return
    async with session_factory() as session:
        group = await _selected_group(session, callback.bot, callback.from_user.id, group_id)
        game = await GameRepository.get_active(session, group.id) if group else None
        if not game:
            await callback.answer("بازی فعالی وجود ندارد.", show_alert=True)
            return
        setattr(game, {"turn": "turn_seconds", "challenge": "challenge_seconds", "extra_challenge": "extra_challenge_seconds"}[kind], value)
        await session.commit()
        from app.handlers.keyboards import game_features_menu
        await callback.message.edit_text(
            "تنظیمات بازی",
            reply_markup=game_features_menu(
                group.id, game.challenge_enabled, game.challenge_mode, game.next_host_enabled,
                game.next_player_enabled, game.next_auto_enabled, game.auto_silence_warnings,
                game.auto_kick_warnings, game.turn_seconds, game.challenge_seconds,
                game.extra_challenge_seconds,
                back_callback=f"game:return_lobby:{game.game_key}" if game.status == "waiting" else f"gameadmin:active:{group.id}",
                game_key=game.game_key,
            ),
        )
    await callback.answer("زمان ذخیره شد.")



@router.callback_query(lambda c: c.data.startswith("gameadmin:extras:"))
async def game_extras_handler(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    group_id = int(callback.data.rsplit(":", 1)[1])
    async with session_factory() as session:
        group = await _selected_group(session, callback.bot, callback.from_user.id, group_id)
        game = await GameRepository.get_active(session, group.id) if group else None
        if not game:
            await callback.answer("بازی فعالی وجود ندارد.", show_alert=True)
            return
        settings = await session.scalar(select(GroupSettings).where(GroupSettings.group_id == group.id))
        custom_emoji = bool(settings and settings.custom_emoji)
        await callback.message.edit_text(
            "✨ <b>امکانات اضافی بازی</b>\n\nگزینه موردنظر را انتخاب کنید.",
            reply_markup=game_extras_menu(
                group.id, game.auto_play, game.turn_color, game.challenge_color,
                game.turn_color_enabled, custom_emoji,
                back_callback=f"gameadmin:active:{group.id}",
            ),
            parse_mode="HTML",
        )
    await callback.answer()

@router.callback_query(lambda c: c.data.startswith("gameadmin:extra:"))
async def game_extra_handler(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer("تنظیم اضافی نامعتبر است.", show_alert=True)
        return
    _, _, group_raw, action = parts
    group_id = int(group_raw)
    async with session_factory() as session:
        group = await _selected_group(session, callback.bot, callback.from_user.id, group_id)
        game = await GameRepository.get_active(session, group.id) if group else None
        if not game:
            await callback.answer("بازی فعالی وجود ندارد.", show_alert=True)
            return
        colors = ["پیش‌فرض", "سبز", "آبی", "بنفش", "قرمز", "طلایی"]
        group_settings = await session.scalar(
            select(GroupSettings).where(GroupSettings.group_id == group.id)
        )
        if group_settings is None:
            group_settings = GroupSettings(group_id=group.id)
            session.add(group_settings)
            await session.flush()

        if action == "auto_play":
            game.auto_play = not game.auto_play
        elif action == "turn_color_enabled":
            game.turn_color_enabled = not game.turn_color_enabled
        elif action == "turn_color":
            game.turn_color = colors[(colors.index(game.turn_color) + 1) % len(colors)] if game.turn_color in colors else colors[0]
        elif action == "challenge_color":
            game.challenge_color = colors[(colors.index(game.challenge_color) + 1) % len(colors)] if game.challenge_color in colors else colors[0]
        elif action == "custom_emoji":
            group_settings.custom_emoji = not group_settings.custom_emoji
        else:
            await callback.answer("امکان اضافی نامعتبر است.", show_alert=True)
            return
        await session.commit()
        await callback.message.edit_text(
            "امکانات اضافی بازی",
            reply_markup=game_extras_menu(group.id, game.auto_play, game.turn_color, game.challenge_color, game.turn_color_enabled, group_settings.custom_emoji),
        )
    await callback.answer("تنظیم ذخیره شد.")

@router.callback_query(lambda c: c.data == "menu:profile")
async def menu_profile(callback: CallbackQuery) -> None:
    if not callback.from_user or not callback.message:
        return
    if callback.message.chat.type != "private":
        await callback.answer("پروفایل فقط در PV قابل استفاده است.", show_alert=True)
        return
    async with session_factory() as session:
        user = await sync_telegram_user(session, callback.from_user)
        username = f"@{user.username}" if user.username else "بدون نام کاربری"
        await callback.message.edit_text(
            f"پروفایل\n\nنام: {user.display_name}\n"
            f"نام کاربری: {username}\n\n"
            f"بازی‌ها: {user.games_played}\n"
            f"بردها: {user.games_won}\n"
            f"چالش‌ها: {user.challenges}",
            reply_markup=main_menu(),
        )
    await callback.answer()


@router.callback_query(lambda c: c.data == "menu:scenarios")
async def menu_scenarios(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    if callback.message.chat.type != "private" or callback.from_user.id not in get_settings().admin_id_set:
        await callback.answer("دسترسی مدیریت این سناریو برای شما مجاز نیست.", show_alert=True)
        return
    await callback.message.edit_text(
        "🎭 مدیریت سناریوها\n\nایجاد، ویرایش یا حذف سناریوهای ذخیره‌شده در دیتابیس.",
        reply_markup=scenario_management_menu(),
    )
    await callback.answer()


@router.callback_query(lambda c: c.data == "menu:bot_settings")
async def bot_settings(callback: CallbackQuery) -> None:
    if not callback.message:
        return
    await callback.message.edit_text(
        "تنظیمات ربات\n\nتنظیمات عمومی و اعلان‌ها از این بخش مدیریت می‌شوند.",
        reply_markup=bot_settings_menu(),
    )
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("botsettings:"))
async def bot_settings_placeholder(callback: CallbackQuery) -> None:
    if not callback.message:
        return
    action = callback.data.split(":", 1)[1]
    if action == "general":
        text = "⚙️ تنظیمات عمومی\n\nتنظیمات شخصی و مسیرهای عمومی ربات از اینجا در دسترس است."
        await callback.message.edit_text(text, reply_markup=general_bot_settings_menu())
    elif action == "notifications":
        async with session_factory() as session:
            user = (await session.execute(select(User).where(User.telegram_id == callback.from_user.id))).scalar_one_or_none()
            if not user:
                await callback.answer("کاربر پیدا نشد.", show_alert=True)
                return
            await callback.message.edit_text("🔔 تنظیمات اعلان‌ها\n\nاعلان‌های موردنظر را فعال یا غیرفعال کنید.", reply_markup=notification_settings_menu(user))
    else:
        await callback.message.edit_text("بخش تنظیمات پیدا نشد.", reply_markup=bot_settings_menu())
    await callback.answer()


@router.callback_query(lambda c: c.data == "menu:ranking")
async def ranking(callback: CallbackQuery) -> None:
    if not callback.message:
        return
    if callback.message.chat.type != "private":
        await callback.answer("رتبه‌بندی فقط در PV قابل استفاده است.", show_alert=True)
        return
    await callback.message.edit_text("رتبه بندی", reply_markup=ranking_menu())
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("ranking:"))
async def ranking_list(callback: CallbackQuery) -> None:
    if not callback.message:
        return
    if callback.message.chat.type != "private":
        await callback.answer("رتبه‌بندی فقط در PV قابل استفاده است.", show_alert=True)
        return
    kind = callback.data.rsplit(":", 1)[1]
    async with session_factory() as session:
        if kind == "mafia":
            order_column = User.mafia_wins
            title = "برترین مافیا"
        elif kind == "citizen":
            order_column = User.citizen_wins
            title = "برترین شهروند"
        else:
            order_column = User.games_won
            title = "بازیکنان برتر"
        result = await session.execute(
            select(User).where(User.is_active.is_(True)).order_by(desc(order_column), desc(User.games_played)).limit(10)
        )
        users = result.scalars().all()
        lines = [title, ""]
        if not users:
            lines.append("هنوز داده‌ای برای رتبه‌بندی ثبت نشده است.")
        else:
            for i, user in enumerate(users, 1):
                score = getattr(user, "games_won" if kind == "players" else f"{kind}_wins")
                lines.append(f"{i}. {user.display_name or user.first_name} — {score}")
        await callback.message.edit_text("\n".join(lines), reply_markup=ranking_menu())
    await callback.answer()


@router.callback_query(lambda c: c.data == "menu:help")
async def menu_help(callback: CallbackQuery) -> None:
    if not callback.message:
        return
    await callback.message.edit_text(
        "راهنما\n\n/newgame — ساخت بازی در گروه\n/profile — مشاهده پروفایل",
        reply_markup=main_menu(),
    )
    await callback.answer()


@router.callback_query(lambda c: c.data == "game:create")
async def menu_create_game(callback: CallbackQuery) -> None:
    if not callback.message:
        return
    await callback.message.answer("ساخت بازی باید داخل گروه انجام شود.\nاز /newgame در گروه استفاده کنید.")
    await callback.answer()


async def game_history_text(session, group) -> str:
    result = await session.execute(
        select(Game, Scenario)
        .join(Scenario, Scenario.id == Game.scenario_id)
        .where(Game.group_id == group.id)
        .order_by(desc(Game.id))
        .limit(10)
    )
    rows = list(result.all())
    if not rows:
        return f"تاریخچه بازی‌های «{group.title}»\n\nهنوز بازی‌ای ثبت نشده است."
    lines = [f"تاریخچه بازی‌های «{group.title}»", ""]
    for game, scenario in rows:
        lines.append(f"#{game.id} — {scenario.name_fa} — {_status_fa(game.status)} — {_phase_fa(game.phase)}")
    return "\n".join(lines)


async def _ensure_draft(session, group, telegram_user_id: int):
    # Handler callbacks provide Telegram user IDs, while Game.user_id /
    # Game.host_user_id are foreign keys to the internal users.id INTEGER.
    # Never use a Telegram ID as a users.id lookup.
    user = await UserRepository(session).get_by_telegram_id(telegram_user_id)
    if user is None:
        return None

    draft = await GameRepository.get_draft(session, group.id, user.id)
    if draft:
        return draft

    settings = await session.scalar(
        select(GroupSettings).where(GroupSettings.group_id == group.id)
    )
    if settings is None:
        settings = GroupSettings(group_id=group.id)
        session.add(settings)
        await session.flush()

    scenario = None
    if settings.default_scenario_id:
        scenario = await session.get(Scenario, settings.default_scenario_id)
        if scenario and (not scenario.enabled or scenario.key == "classic"):
            scenario = None
    if scenario is None:
        scenario = (await session.execute(
            select(Scenario).where(Scenario.enabled.is_(True), Scenario.key != "classic").order_by(Scenario.id)
        )).scalars().first()
    if not scenario:
        return None
    return await create_game(session, group, scenario, user, status="draft")


async def render_new_game_menu(session, group, user_id: int | None = None):
    if user_id is not None:
        await _ensure_draft(session, group, user_id)
    internal_user_id = None
    if user_id is not None:
        user = await UserRepository(session).get_by_telegram_id(user_id)
        internal_user_id = user.id if user else None
    draft = await GameRepository.get_draft(session, group.id, internal_user_id)
    if not draft:
        return "امکان ایجاد پیش‌نویس بازی وجود ندارد."
    scenario = await session.get(Scenario, draft.scenario_id)
    host = await session.get(User, draft.host_user_id) if draft.host_user_id else None
    emojis = _emoji_settings(draft)
    emoji_count = sum(1 for value in emojis.values() if value)
    return (
        "ایجاد بازی\n\n"
        f"سناریو: {scenario.name_fa if scenario else 'انتخاب نشده'}\n"
        f"گرداننده: {host.display_name if host else 'انتخاب نشده'}\n"
        f"چالش: {'فعال' if draft.challenge_enabled else 'غیرفعال'}\n"
        f"نکست گرداننده: {'فعال' if draft.next_host_enabled else 'غیرفعال'}\n"
        f"نکست بازیکن: {'فعال' if draft.next_player_enabled else 'غیرفعال'}\n"
        f"نکست خودکار: {'فعال' if draft.next_auto_enabled else 'غیرفعال'}\n"
        f"بازی خودکار شب: {'فعال' if draft.auto_play else 'غیرفعال'}\n"
        f"اموجی‌های وضعیت: {emoji_count}/7 فعال"
    )


async def _require_group_admin(callback: CallbackQuery, session, group_id: int):
    if not callback.from_user:
        return None
    group = await _selected_group(session, callback.bot, callback.from_user.id, group_id)
    if not group:
        await callback.answer("دسترسی مدیریت گروه تأیید نشد.", show_alert=True)
        return None
    return group


@router.callback_query(lambda c: c.data and c.data.startswith("newgame:menu:"))
async def new_game_menu_handler(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    group_id = int(callback.data.rsplit(":", 1)[1])
    async with session_factory() as session:
        group = await _require_group_admin(callback, session, group_id)
        if not group:
            return
        text = await render_new_game_menu(session, group, callback.from_user.id)
        from app.handlers.keyboards import new_game_menu
        await callback.message.edit_text(text, reply_markup=new_game_menu(group.id))
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("newgame:scenario:"))
async def new_game_scenario(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    group_id = int(callback.data.rsplit(":", 1)[1])
    async with session_factory() as session:
        group = await _require_group_admin(callback, session, group_id)
        if not group:
            return
        result = await session.execute(select(Scenario).where(Scenario.enabled.is_(True), Scenario.key != "classic").order_by(Scenario.id))
        scenarios = result.scalars().all()
        await callback.message.edit_text("انتخاب سناریو", reply_markup=__import__("app.handlers.keyboards", fromlist=["scenario_select_keyboard"]).scenario_select_keyboard(group.id, scenarios))
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("newgame:setscenario:"))
async def new_game_set_scenario(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    parts = callback.data.split(":")
    if len(parts) != 4 or parts[0] != "newgame" or parts[1] != "setscenario":
        await callback.answer("درخواست انتخاب سناریو نامعتبر است.", show_alert=True)
        return
    _, _, group_raw, scenario_raw = parts
    try:
        group_id, scenario_id = int(group_raw), int(scenario_raw)
    except ValueError:
        await callback.answer("شناسه سناریو نامعتبر است.", show_alert=True)
        return
    async with session_factory() as session:
        group = await _require_group_admin(callback, session, group_id)
        if not group:
            return
        draft = await _ensure_draft(session, group, callback.from_user.id)
        scenario = await session.get(Scenario, scenario_id)
        if not draft or not scenario or not scenario.enabled or scenario.key == "classic":
            await callback.answer("سناریو قابل انتخاب نیست.", show_alert=True)
            return
        draft.scenario_id = scenario.id
        await session.commit()
        text = await render_new_game_menu(session, group, callback.from_user.id)
        await callback.message.edit_text(text, reply_markup=__import__("app.handlers.keyboards", fromlist=["new_game_menu"]).new_game_menu(group.id))
    await callback.answer("سناریو انتخاب شد.")


@router.callback_query(lambda c: c.data and c.data.startswith("newgame:host:"))
async def new_game_host(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    group_id = int(callback.data.rsplit(":", 1)[1])
    async with session_factory() as session:
        group = await _require_group_admin(callback, session, group_id)
        if not group:
            return
        admins = await callback.bot.get_chat_administrators(group.telegram_id)
        await callback.message.edit_text("انتخاب گرداننده", reply_markup=__import__("app.handlers.keyboards", fromlist=["host_select_keyboard"]).host_select_keyboard(group.id, admins))
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("newgame:sethost:"))
async def new_game_set_host(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    parts = callback.data.split(":")
    if len(parts) != 4 or parts[0] != "newgame" or parts[1] != "sethost":
        await callback.answer("درخواست انتخاب گرداننده نامعتبر است.", show_alert=True)
        return
    _, _, group_raw, user_raw = parts
    try:
        group_id, host_tid = int(group_raw), int(user_raw)
    except ValueError:
        await callback.answer("شناسه گرداننده نامعتبر است.", show_alert=True)
        return
    async with session_factory() as session:
        group = await _require_group_admin(callback, session, group_id)
        if not group:
            return
        draft = await _ensure_draft(session, group, callback.from_user.id)
        if not draft:
            await callback.answer("پیش‌نویس بازی پیدا نشد.", show_alert=True)
            return
        try:
            member = await callback.bot.get_chat_member(group.telegram_id, host_tid)
        except Exception:
            await callback.answer("اطلاعات گرداننده از تلگرام قابل دریافت نیست.", show_alert=True)
            return
        if member.status not in ("creator", "administrator"):
            await callback.answer("گرداننده باید مدیر گروه باشد.", show_alert=True)
            return
        tg_user = member.user
        host = await UserRepository(session).upsert_from_telegram(
            tg_user.id,
            tg_user.username,
            tg_user.first_name or "",
            tg_user.last_name,
        )
        draft.host_user_id = host.id
        await session.commit()
        text = await render_new_game_menu(session, group, callback.from_user.id)
        await callback.message.edit_text(text, reply_markup=__import__("app.handlers.keyboards", fromlist=["new_game_menu"]).new_game_menu(group.id))
    await callback.answer("گرداننده انتخاب شد.")


@router.callback_query(lambda c: c.data and c.data.startswith("newgame:settings:"))
async def new_game_settings(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    group_id = int(callback.data.rsplit(":", 1)[1])
    async with session_factory() as session:
        group = await _require_group_admin(callback, session, group_id)
        if not group:
            return
        draft = await _ensure_draft(session, group, callback.from_user.id)
        await callback.message.edit_text(
            "تنظیمات بازی",
            reply_markup=__import__("app.handlers.keyboards", fromlist=["new_game_settings_keyboard"]).new_game_settings_keyboard(
                group.id,
                draft.challenge_enabled if draft else True,
                draft.next_host_enabled if draft else True,
                draft.next_player_enabled if draft else True,
                draft.next_auto_enabled if draft else False,
                draft.auto_play if draft else False,
                draft.turn_seconds if draft else 120,
                draft.challenge_seconds if draft else 60,
                draft.extra_challenge_seconds if draft else 60,
            ),
        )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("newgame:toggle_challenge:"))
async def toggle_draft_challenge(callback: CallbackQuery) -> None:
    group_id = int(callback.data.rsplit(":", 1)[1])
    async with session_factory() as session:
        group = await _require_group_admin(callback, session, group_id)
        if not group: return
        draft = await _ensure_draft(session, group, callback.from_user.id)
        draft.challenge_enabled = not draft.challenge_enabled
        await session.commit()
        from app.handlers.keyboards import new_game_settings_keyboard
        await callback.message.edit_reply_markup(reply_markup=new_game_settings_keyboard(
            group.id, draft.challenge_enabled, draft.next_host_enabled,
            draft.next_player_enabled, draft.next_auto_enabled, draft.auto_play, draft.turn_seconds, draft.challenge_seconds, draft.extra_challenge_seconds))
    await callback.answer("وضعیت چالش تغییر کرد.")


@router.callback_query(lambda c: c.data and c.data.startswith("newgame:toggle_host_next:"))
async def toggle_draft_host_next(callback: CallbackQuery) -> None:
    group_id = int(callback.data.rsplit(":", 1)[1])
    async with session_factory() as session:
        group = await _require_group_admin(callback, session, group_id)
        if not group: return
        draft = await _ensure_draft(session, group, callback.from_user.id)
        draft.next_host_enabled = not draft.next_host_enabled
        await session.commit()
        from app.handlers.keyboards import new_game_settings_keyboard
        await callback.message.edit_reply_markup(reply_markup=new_game_settings_keyboard(
            group.id, draft.challenge_enabled, draft.next_host_enabled,
            draft.next_player_enabled, draft.next_auto_enabled, draft.auto_play,
            draft.turn_seconds, draft.challenge_seconds, draft.extra_challenge_seconds))
    await callback.answer("نکست گرداننده تغییر کرد.")


@router.callback_query(lambda c: c.data and c.data.startswith("newgame:toggle_player_next:"))
async def toggle_draft_player_next(callback: CallbackQuery) -> None:
    group_id = int(callback.data.rsplit(":", 1)[1])
    async with session_factory() as session:
        group = await _require_group_admin(callback, session, group_id)
        if not group: return
        draft = await _ensure_draft(session, group, callback.from_user.id)
        draft.next_player_enabled = not draft.next_player_enabled
        await session.commit()
        from app.handlers.keyboards import new_game_settings_keyboard
        await callback.message.edit_reply_markup(reply_markup=new_game_settings_keyboard(
            group.id, draft.challenge_enabled, draft.next_host_enabled,
            draft.next_player_enabled, draft.next_auto_enabled, draft.auto_play,
            draft.turn_seconds, draft.challenge_seconds, draft.extra_challenge_seconds))
    await callback.answer("نکست بازیکن تغییر کرد.")


@router.callback_query(lambda c: c.data and c.data.startswith("newgame:toggle_auto_next:"))
async def toggle_draft_auto_next(callback: CallbackQuery) -> None:
    group_id = int(callback.data.rsplit(":", 1)[1])
    async with session_factory() as session:
        group = await _require_group_admin(callback, session, group_id)
        if not group: return
        draft = await _ensure_draft(session, group, callback.from_user.id)
        draft.next_auto_enabled = not draft.next_auto_enabled
        await session.commit()
        from app.handlers.keyboards import new_game_settings_keyboard
        await callback.message.edit_reply_markup(reply_markup=new_game_settings_keyboard(
            group.id, draft.challenge_enabled, draft.next_host_enabled,
            draft.next_player_enabled, draft.next_auto_enabled, draft.auto_play,
            draft.turn_seconds, draft.challenge_seconds, draft.extra_challenge_seconds))
    await callback.answer("نکست خودکار تغییر کرد.")


@router.callback_query(lambda c: c.data and c.data.startswith("newgame:time:"))
async def new_game_time_menu(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer("تنظیم زمان نامعتبر است.", show_alert=True)
        return
    _, _, group_raw, kind = parts
    group_id = int(group_raw)
    async with session_factory() as session:
        group = await _require_group_admin(callback, session, group_id)
        if not group:
            return
        draft = await _ensure_draft(session, group, callback.from_user.id)
        if not draft:
            await callback.answer("پیش‌نویس بازی پیدا نشد.", show_alert=True)
            return
        current = {
            "turn": draft.turn_seconds,
            "challenge": draft.challenge_seconds,
            "extra_challenge": draft.extra_challenge_seconds,
        }.get(kind)
        if current is None:
            await callback.answer("نوع زمان نامعتبر است.", show_alert=True)
            return
        from app.handlers.keyboards import duration_keyboard
        await callback.message.edit_text(
            "انتخاب زمان " + {"turn": "نوبت", "challenge": "چالش", "extra_challenge": "چالش اضافه"}[kind],
            reply_markup=duration_keyboard("newgame", group.id, kind, current, f"newgame:settings:{group.id}"),
        )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("newgame:set_time:"))
async def new_game_set_time(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    if len(parts) != 5:
        await callback.answer("تنظیم زمان نامعتبر است.", show_alert=True)
        return
    _, _, group_raw, kind, value_raw = parts
    group_id, value = int(group_raw), int(value_raw)
    if kind not in {"turn", "challenge", "extra_challenge"} or not 15 <= value <= 600:
        await callback.answer("مقدار زمان نامعتبر است.", show_alert=True)
        return
    async with session_factory() as session:
        group = await _require_group_admin(callback, session, group_id)
        if not group:
            return
        draft = await _ensure_draft(session, group, callback.from_user.id)
        setattr(draft, {"turn": "turn_seconds", "challenge": "challenge_seconds", "extra_challenge": "extra_challenge_seconds"}[kind], value)
        await session.commit()
        from app.handlers.keyboards import new_game_settings_keyboard
        await callback.message.edit_text(
            "تنظیمات بازی",
            reply_markup=new_game_settings_keyboard(
                group.id, draft.challenge_enabled, draft.next_host_enabled, draft.next_player_enabled,
                draft.next_auto_enabled, draft.auto_play, draft.turn_seconds, draft.challenge_seconds,
                draft.extra_challenge_seconds,
            ),
        )
    await callback.answer("زمان ذخیره شد.")


@router.callback_query(lambda c: c.data and c.data.startswith("newgame:extras:"))
async def new_game_extras_handler(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    group_id = int(callback.data.rsplit(":", 1)[1])
    async with session_factory() as session:
        group = await _require_group_admin(callback, session, group_id)
        if not group:
            return
        draft = await _ensure_draft(session, group, callback.from_user.id)
        await callback.message.edit_text(
            "امکانات اضافه",
            reply_markup=__import__("app.handlers.keyboards", fromlist=["new_game_extras_keyboard"]).new_game_extras_keyboard(group.id, draft.turn_color, draft.challenge_color, any(_emoji_settings(draft).values())),
        )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("newgame:toggle_auto:"))
async def toggle_draft_auto(callback: CallbackQuery) -> None:
    group_id = int(callback.data.rsplit(":", 1)[1])
    async with session_factory() as session:
        group = await _require_group_admin(callback, session, group_id)
        if not group: return
        draft = await _ensure_draft(session, group, callback.from_user.id)
        draft.auto_play = not draft.auto_play
        await session.commit()
        from app.handlers.keyboards import new_game_settings_keyboard
        await callback.message.edit_reply_markup(reply_markup=new_game_settings_keyboard(
            group.id, draft.challenge_enabled, draft.next_host_enabled,
            draft.next_player_enabled, draft.next_auto_enabled, draft.auto_play,
            draft.turn_seconds, draft.challenge_seconds, draft.extra_challenge_seconds))
    await callback.answer("بازی خودکار تغییر کرد.")


@router.callback_query(lambda c: c.data and c.data.startswith("newgame:emoji:"))
async def new_game_emoji_handler(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    group_id = int(callback.data.rsplit(":", 1)[1])
    async with session_factory() as session:
        group = await _require_group_admin(callback, session, group_id)
        if not group:
            return
        draft = await _ensure_draft(session, group, callback.from_user.id)
        if not draft:
            await callback.answer("پیش‌نویس بازی پیدا نشد.", show_alert=True)
            return
        from app.handlers.keyboards import new_game_emoji_menu
        await callback.message.edit_text(
            "اموجی‌های وضعیت و اکت‌ها\n\n"
            "این تنظیمات برای بازی فعلی از زمان ایجاد لابی ذخیره می‌شوند.",
            reply_markup=new_game_emoji_menu(group.id, _emoji_settings(draft)),
        )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("newgame:emoji_toggle:"))
async def new_game_emoji_toggle(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer("تنظیم اموجی نامعتبر است.", show_alert=True)
        return
    _, _, group_raw, key = parts
    try:
        group_id = int(group_raw)
    except ValueError:
        await callback.answer("شناسه گروه نامعتبر است.", show_alert=True)
        return
    async with session_factory() as session:
        group = await _require_group_admin(callback, session, group_id)
        if not group:
            return
        draft = await _ensure_draft(session, group, callback.from_user.id)
        settings = _emoji_settings(draft)
        if key not in settings:
            await callback.answer("اموجی نامعتبر است.", show_alert=True)
            return
        settings[key] = not settings[key]
        draft.emoji_settings = json.dumps(settings, ensure_ascii=False)
        await session.commit()
        from app.handlers.keyboards import new_game_emoji_menu
        await callback.message.edit_reply_markup(reply_markup=new_game_emoji_menu(group.id, settings))
    await callback.answer("تنظیم اموجی ذخیره شد.")


@router.callback_query(lambda c: c.data and c.data.startswith("newgame:toggle_emoji:"))
async def toggle_draft_emoji_legacy(callback: CallbackQuery) -> None:
    # Backward compatibility for old callback buttons.
    group_id = int(callback.data.rsplit(":", 1)[1])
    async with session_factory() as session:
        group = await _require_group_admin(callback, session, group_id)
        if not group:
            return
        draft = await _ensure_draft(session, group, callback.from_user.id)
        settings = _emoji_settings(draft)
        settings["challenge"] = not settings["challenge"]
        draft.emoji_settings = json.dumps(settings, ensure_ascii=False)
        await session.commit()
    await callback.answer("وضعیت اموجی چالش تغییر کرد.")


@router.callback_query(lambda c: c.data and c.data.startswith("newgame:turn_color:"))
async def new_game_turn_color(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    group_id = int(callback.data.rsplit(":", 1)[1])
    async with session_factory() as session:
        group = await _require_group_admin(callback, session, group_id)
        if not group:
            return
        draft = await _ensure_draft(session, group, callback.from_user.id)
        if not draft:
            await callback.answer("پیش‌نویس بازی پیدا نشد.", show_alert=True)
            return
        from app.handlers.keyboards import new_game_color_keyboard
        await callback.message.edit_text(
            "انتخاب رنگ نوبت",
            reply_markup=new_game_color_keyboard(group.id, "turn", draft.turn_color),
        )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("newgame:challenge_color:"))
async def new_game_challenge_color(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    group_id = int(callback.data.rsplit(":", 1)[1])
    async with session_factory() as session:
        group = await _require_group_admin(callback, session, group_id)
        if not group:
            return
        draft = await _ensure_draft(session, group, callback.from_user.id)
        if not draft:
            await callback.answer("پیش‌نویس بازی پیدا نشد.", show_alert=True)
            return
        from app.handlers.keyboards import new_game_color_keyboard
        await callback.message.edit_text(
            "انتخاب رنگ چالش",
            reply_markup=new_game_color_keyboard(group.id, "challenge", draft.challenge_color),
        )
    await callback.answer()


async def _set_new_game_color(callback: CallbackQuery, kind: str) -> None:
    if not callback.message or not callback.from_user:
        return
    parts = callback.data.split(":", 3)
    if len(parts) != 4 or parts[0] != "newgame" or parts[1] not in {"set_turn_color", "set_challenge_color"}:
        await callback.answer("تنظیم رنگ نامعتبر است.", show_alert=True)
        return
    _, _, group_raw, value = parts
    try:
        group_id = int(group_raw)
    except ValueError:
        await callback.answer("شناسه گروه نامعتبر است.", show_alert=True)
        return
    allowed = {"پیش‌فرض", "قرمز", "آبی", "سبز", "زرد", "بنفش"}
    if value not in allowed:
        await callback.answer("رنگ نامعتبر است.", show_alert=True)
        return
    async with session_factory() as session:
        group = await _require_group_admin(callback, session, group_id)
        if not group:
            return
        draft = await _ensure_draft(session, group, callback.from_user.id)
        if not draft:
            await callback.answer("پیش‌نویس بازی پیدا نشد.", show_alert=True)
            return
        if kind == "turn":
            draft.turn_color = value
        else:
            draft.challenge_color = value
        await session.commit()
        from app.handlers.keyboards import new_game_extras_keyboard
        await callback.message.edit_text(
            "امکانات اضافه",
            reply_markup=new_game_extras_keyboard(
                group.id, draft.turn_color, draft.challenge_color,
                any(_emoji_settings(draft).values())
            ),
        )
    await callback.answer("تنظیم ذخیره شد.")


@router.callback_query(lambda c: c.data and c.data.startswith("newgame:set_turn_color:"))
async def new_game_set_turn_color(callback: CallbackQuery) -> None:
    await _set_new_game_color(callback, "turn")


@router.callback_query(lambda c: c.data and c.data.startswith("newgame:set_challenge_color:"))
async def new_game_set_challenge_color(callback: CallbackQuery) -> None:
    await _set_new_game_color(callback, "challenge")


@router.callback_query(lambda c: c.data and c.data.startswith("newgame:create:"))
async def new_game_create(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    group_id = int(callback.data.rsplit(":", 1)[1])
    async with session_factory() as session:
        group = await _require_group_admin(callback, session, group_id)
        if not group:
            return
        active = await GameRepository.get_active(session, group.id)
        if active:
            await callback.answer("این گروه در حال حاضر بازی فعالی دارد.", show_alert=True)
            return
        draft = await _ensure_draft(session, group, callback.from_user.id)
        if not draft:
            await callback.answer("پیش‌نویس بازی پیدا نشد.", show_alert=True)
            return
        scenario = await session.get(Scenario, draft.scenario_id)
        if not scenario:
            await callback.answer("سناریو انتخاب نشده است.", show_alert=True)
            return
        host = await session.get(User, draft.host_user_id)
        if not host:
            await callback.answer("گرداننده انتخاب نشده است.", show_alert=True)
            return
        draft.status = "waiting"
        draft.phase = "lobby"
        await session.commit()
        from app.handlers.keyboards import lobby_keyboard_v2
        text, _ = await __import__("app.services.game", fromlist=["render_lobby"]).render_lobby(session, draft)
        await callback.message.edit_text(text, reply_markup=lobby_keyboard_v2(draft.game_key, scenario, await GameRepository.players(session, draft.id), await GameRepository.reserves(session, draft.id), is_host=callback.from_user.id == host.telegram_id, can_deal=False, reserve_enabled=draft.reserve_enabled, training_url=scenario.training_url, telegram_training_url=scenario.telegram_training_url))
    await callback.answer("لابی بازی ایجاد شد.")


@router.callback_query(lambda c: c.data and c.data.startswith("groupstart:history:"))
async def group_start_history(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    group_id = int(callback.data.rsplit(":", 1)[1])
    async with session_factory() as session:
        group = await _require_group_admin(callback, session, group_id)
        if not group:
            return
        await callback.message.edit_text(await game_history_text(session, group), reply_markup=__import__("app.handlers.keyboards", fromlist=["group_start_menu"]).group_start_menu(group.id))
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("newgame:turn_color:"))
async def draft_turn_color(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    group_id = int(callback.data.rsplit(":", 1)[1])
    colors = ["پیش‌فرض", "سبز", "آبی", "بنفش", "قرمز", "طلایی"]
    async with session_factory() as session:
        group = await _require_group_admin(callback, session, group_id)
        if not group:
            return
        draft = await _ensure_draft(session, group, callback.from_user.id)
        draft.turn_color = colors[(colors.index(draft.turn_color) + 1) % len(colors)] if draft.turn_color in colors else colors[0]
        await session.commit()
        await callback.message.edit_reply_markup(reply_markup=__import__("app.handlers.keyboards", fromlist=["new_game_extras_keyboard"]).new_game_extras_keyboard(group.id, draft.turn_color, draft.challenge_color, any(_emoji_settings(draft).values())))
    await callback.answer("رنگ نوبت تغییر کرد.")


@router.callback_query(lambda c: c.data and c.data.startswith("newgame:challenge_color:"))
async def draft_challenge_color(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    group_id = int(callback.data.rsplit(":", 1)[1])
    colors = ["پیش‌فرض", "سبز", "آبی", "بنفش", "قرمز", "طلایی"]
    async with session_factory() as session:
        group = await _require_group_admin(callback, session, group_id)
        if not group:
            return
        draft = await _ensure_draft(session, group, callback.from_user.id)
        draft.challenge_color = colors[(colors.index(draft.challenge_color) + 1) % len(colors)] if draft.challenge_color in colors else colors[0]
        await session.commit()
        await callback.message.edit_reply_markup(reply_markup=__import__("app.handlers.keyboards", fromlist=["new_game_extras_keyboard"]).new_game_extras_keyboard(group.id, draft.turn_color, draft.challenge_color, json.loads(draft.emoji_settings or "{}").get("challenge", True)))
    await callback.answer("رنگ چالش تغییر کرد.")
 

def _parse_duration(value: str) -> int | None:
    value = value.strip().lower().replace("دقیقه", "m").replace("ثانیه", "s")
    if ":" in value:
        parts = value.split(":")
        if len(parts) == 2 and all(part.isdigit() for part in parts):
            minutes, seconds = map(int, parts)
            if 0 <= seconds < 60:
                return minutes * 60 + seconds
        return None
    try:
        if value.endswith("m"):
            return int(value[:-1]) * 60
        if value.endswith("s"):
            return int(value[:-1])
        return int(value)
    except ValueError:
        return None


def _format_duration(seconds: int) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def _parse_scenario_roles(text: str) -> list[tuple[str, str]]:
    rows = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = line.rsplit(maxsplit=1)
        if len(parts) != 2:
            raise ValueError(f"فرمت این سطر نادرست است: «{line}»")
        role_name, team = parts
        team_map = {
            "مافیا": "mafia", "maf": "mafia", "mafia": "mafia",
            "شهروند": "citizen", "سایدشهروند": "citizen", "citizen": "citizen",
            "مستقل": "independent", "independent": "independent",
        }
        team_key = team_map.get(team.strip().lower())
        if not team_key or not role_name.strip():
            raise ValueError(f"ساید «{team}» معتبر نیست. فقط مافیا، شهروند یا مستقل.")
        rows.append((role_name.strip(), team_key))
    return rows


async def _scenario_roles_text(session, scenario_id: int) -> str:
    rows = (await session.execute(
        select(ScenarioRole, Role)
        .join(Role, Role.id == ScenarioRole.role_id)
        .where(ScenarioRole.scenario_id == scenario_id)
        .order_by(ScenarioRole.position, ScenarioRole.id)
    )).all()
    team_names = {"mafia": "مافیا", "citizen": "شهروند", "independent": "مستقل"}
    lines = []
    for _row, role in rows:
        count = max(1, _row.count)
        for _ in range(count):
            lines.append(f"{role.name_fa} {team_names.get(role.team, role.team)}")
    return "\n".join(lines)

async def _scenario_context_group_id(callback: CallbackQuery, state: FSMContext | None = None) -> int | None:
    """Resolve the group context carried by scenario-management callbacks/FSM."""
    if state is not None:
        data = await state.get_data()
        value = data.get("group_scenario_group_id")
        if value:
            try:
                return int(value)
            except (TypeError, ValueError):
                pass
    data = str(callback.data or "")
    parts = data.split(":")
    if len(parts) >= 3 and parts[0] == "scenario_admin":
        action = parts[1]
        # Top-level group-scoped entries carry the group id directly.
        if action in {"create", "edit", "delete", "roles", "training", "cancel"} and len(parts) == 3:
            try:
                return int(parts[2])
            except (TypeError, ValueError):
                pass
        # Selection/confirmation callbacks carry scenario id then group id.
        if action in {"edit", "delete", "delete_confirm", "role_list", "training_select"} and len(parts) >= 4:
            try:
                return int(parts[-1])
            except (TypeError, ValueError):
                pass
    return None


async def _scenario_admin_allowed(callback: CallbackQuery, state: FSMContext | None = None) -> bool:
    if not callback.from_user or not callback.message or callback.message.chat.type != "private":
        return False
    if callback.from_user.id in get_settings().admin_id_set:
        return True
    group_id = await _scenario_context_group_id(callback, state)
    if not group_id:
        return False
    async with session_factory() as session:
        group = await session.get(Group, int(group_id))
        if not group:
            return False
        return await _is_group_admin(callback.bot, group, callback.from_user.id)

async def _scenario_management_markup(session, group_id: int | None):
    if group_id:
        scenarios = list((await session.execute(
            select(Scenario).where(Scenario.enabled.is_(True), Scenario.key != "classic").order_by(Scenario.id)
        )).scalars().all())
        return group_scenario_management_menu(int(group_id), scenarios)
    return scenario_management_menu()

async def _scenario_form_roles(session, scenario_id: int) -> dict[int, int]:
    rows = (await session.execute(
        select(ScenarioRole).where(ScenarioRole.scenario_id == scenario_id).order_by(ScenarioRole.position, ScenarioRole.id)
    )).scalars().all()
    return {row.role_id: row.count for row in rows}

@router.callback_query(lambda c: c.data == "scenario_admin:create" or c.data.startswith("scenario_admin:create:"))
async def scenario_create_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _scenario_admin_allowed(callback, state):
        await callback.answer("دسترسی فقط برای مدیر ربات است.", show_alert=True)
        return
    group_id = await _scenario_context_group_id(callback, state)
    previous = await state.get_data()
    await state.clear()
    await state.set_state(ScenarioAdminState.name)
    await state.update_data(mode="create", group_scenario_group_id=group_id or previous.get("group_scenario_group_id"))
    await callback.message.edit_text("➕ ایجاد سناریو\n\nنام سناریو را ارسال کنید:")
    await callback.answer()

@router.callback_query(lambda c: c.data == "scenario_admin:edit" or c.data.startswith("scenario_admin:edit:"))
async def scenario_edit_list(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _scenario_admin_allowed(callback, state):
        await callback.answer("دسترسی فقط برای مدیر ربات است.", show_alert=True)
        return
    async with session_factory() as session:
        scenarios = list((await session.execute(select(Scenario).where(Scenario.key != "classic").order_by(Scenario.id))).scalars().all())
    await callback.message.edit_text("✏️ سناریوی موردنظر را انتخاب کنید:", reply_markup=scenario_admin_list_keyboard(scenarios, "edit", await _scenario_context_group_id(callback, state)))
    await callback.answer()

@router.callback_query(lambda c: c.data == "scenario_admin:delete" or c.data.startswith("scenario_admin:delete:"))
async def scenario_delete_list(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _scenario_admin_allowed(callback, state):
        await callback.answer("دسترسی فقط برای مدیر ربات است.", show_alert=True)
        return
    async with session_factory() as session:
        scenarios = list((await session.execute(select(Scenario).where(Scenario.key != "classic").order_by(Scenario.id))).scalars().all())
    await callback.message.edit_text("🗑 سناریوی موردنظر را برای حذف انتخاب کنید:", reply_markup=scenario_admin_list_keyboard(scenarios, "delete", await _scenario_context_group_id(callback, state)))
    await callback.answer()

@router.callback_query(lambda c: c.data == "scenario_admin:cancel" or c.data.startswith("scenario_admin:cancel:"))
async def scenario_admin_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    group_id = data.get("group_scenario_group_id") or await _scenario_context_group_id(callback, None)
    await state.clear()
    if group_id:
        async with session_factory() as session:
            group = await session.get(Group, int(group_id))
            scenarios = list((await session.execute(
                select(Scenario).where(Scenario.enabled.is_(True), Scenario.key != "classic").order_by(Scenario.id)
            )).scalars().all())
        await callback.message.edit_text(
            "🎭 مدیریت سناریوی گروه",
            reply_markup=group_scenario_management_menu(int(group_id), scenarios),
        )
    else:
        await callback.message.edit_text("🎭 مدیریت سناریوها", reply_markup=scenario_management_menu())
    await callback.answer()


@router.message(ScenarioAdminState.name)
async def scenario_form_name(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    group_id = data.get("group_scenario_group_id")
    allowed = bool(message.chat.type == "private" and message.from_user and message.from_user.id in get_settings().admin_id_set)
    if not allowed and group_id:
        async with session_factory() as _auth_session:
            _group = await _auth_session.get(Group, int(group_id))
            allowed = bool(_group and message.from_user and await _is_group_admin(message.bot, _group, message.from_user.id))
    if not allowed:
        return
    value = (message.text or "").strip()
    data = await state.get_data()
    if value == "/cancel":
        await state.clear()
        await message.answer("لغو شد.", reply_markup=scenario_management_menu())
        return
    if value == "-" and data.get("edit_id"):
        value = data.get("current_name", "")
    if not 2 <= len(value) <= 80:
        await message.answer("نام سناریو باید بین ۲ تا ۸۰ کاراکتر باشد.")
        return
    await state.update_data(name=value)
    await state.set_state(ScenarioAdminState.description)
    await message.answer("توضیحات سناریو را ارسال کنید. برای بدون تغییر در ویرایش، - بفرستید:")

@router.message(ScenarioAdminState.description)
async def scenario_form_description(message: Message, state: FSMContext) -> None:
    if message.chat.type != "private":
        return
    value = (message.text or "").strip()
    data = await state.get_data()
    if value == "/cancel":
        await state.clear()
        await message.answer("لغو شد.", reply_markup=scenario_management_menu())
        return
    if value == "-" and data.get("edit_id"):
        value = data.get("current_description", "")
    await state.update_data(description=value)
    await state.set_state(ScenarioAdminState.roles)
    current = data.get("current_roles_text", "")
    await message.answer(
        "🎭 حالا نقش‌ها و سایدها را وارد کن؛ هر نقش در یک خط.\n\n"
        "مثال:\nدکتر واتسون شهروند\nپدرخوانده مافیا\nنوستراداموس مستقل\n\n"
        "کلمه آخر هر خط ساید است و بقیه نام نقش.\n"
        + ("\nترکیب فعلی:\n" + current if current else "")
        + ("\n\nبرای بدون تغییر، - بفرست." if data.get("edit_id") else "")
    )

@router.message(ScenarioAdminState.min_players)
async def scenario_form_min(message: Message, state: FSMContext) -> None:
    # Kept as a compatibility state; new forms derive player count from roles.
    await state.set_state(ScenarioAdminState.turn_time)
    await message.answer("زمان هر نوبت را فقط به‌صورت تعداد ثانیه وارد کنید. مثال: 120\nپیش‌فرض: 120")

@router.message(ScenarioAdminState.turn_time)
async def scenario_form_turn_time(message: Message, state: FSMContext) -> None:
    value = (message.text or "").strip()
    data = await state.get_data()
    if value in {"", "-"}:
        value = str(data.get("current_turn_seconds", 120) if data.get("edit_id") else 120)
    seconds = _parse_duration(value)
    if seconds is None or not 15 <= seconds <= 600:
        await message.answer("زمان نوبت باید بین ۱۵ ثانیه تا ۱۰ دقیقه باشد. مثال: 02:00")
        return
    await state.update_data(turn_seconds=seconds)
    await state.set_state(ScenarioAdminState.challenge_time)
    await message.answer("زمان چالش را فقط به‌صورت تعداد ثانیه وارد کنید. مثال: 60\nپیش‌فرض: 60")

@router.message(ScenarioAdminState.challenge_time)
async def scenario_form_challenge_time(message: Message, state: FSMContext) -> None:
    value = (message.text or "").strip()
    data = await state.get_data()
    if value in {"", "-"}:
        value = str(data.get("current_challenge_seconds", 60) if data.get("edit_id") else 60)
    seconds = _parse_duration(value)
    if seconds is None or not 15 <= seconds <= 600:
        await message.answer("زمان چالش باید بین ۱۵ ثانیه تا ۱۰ دقیقه باشد. مثال: 01:00")
        return
    await state.update_data(challenge_seconds=seconds)
    await state.set_state(ScenarioAdminState.extra_challenge_time)
    await message.answer("زمان چالش اضافه را فقط به‌صورت تعداد ثانیه وارد کنید. مثال: 60\nپیش‌فرض: 60")

@router.message(ScenarioAdminState.extra_challenge_time)
async def scenario_form_extra_challenge_time(message: Message, state: FSMContext) -> None:
    value = (message.text or "").strip()
    data = await state.get_data()
    if value in {"", "-"}:
        value = str(data.get("current_extra_challenge_seconds", 60) if data.get("edit_id") else 60)
    seconds = _parse_duration(value)
    if seconds is None or not 15 <= seconds <= 600:
        await message.answer("زمان چالش اضافه باید بین ۱۵ ثانیه تا ۱۰ دقیقه باشد. مثال: 01:00")
        return
    await state.update_data(extra_challenge_seconds=seconds)
    await state.set_state(ScenarioAdminState.confirm)
    data = await state.get_data()
    roles_text = data.get("current_roles_text", "")
    role_count = len(data.get("role_ids", []))
    challenge_label = {"limited": "محدود (۱ چالش)", "free": "آزاد", "off": "بدون چالش"}.get(data.get("challenge_mode"), "محدود")
    await message.answer(
        f"📋 <b>خلاصه سناریو</b>\n\n"
        f"🎭 نام: {data.get('name', '—')}\n"
        f"📝 توضیحات: {data.get('description') or '—'}\n"
        f"👥 تعداد نفرات: {role_count}\n"
        f"🤏 چالش: {challenge_label}\n"
        f"⏱ نوبت: {_format_duration(int(data.get('turn_seconds', 120)))}\n"
        f"⏱ زمان چالش: {_format_duration(int(data.get('challenge_seconds', 60)))}\n"
        f"➕ چالش اضافه: {_format_duration(int(data.get('extra_challenge_seconds', 60)))}\n\n"
        "اگر همه‌چیز درست است تأیید کن.",
        reply_markup=scenario_confirm_keyboard("edit" if data.get("edit_id") else "create"),
    )

@router.message(ScenarioAdminState.max_players)
async def scenario_form_max(message: Message, state: FSMContext) -> None:
    await scenario_form_min(message, state)

@router.callback_query(lambda c: c.data.startswith("scenario_admin:") and ":challenge:" in c.data)
async def scenario_form_challenge(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _scenario_admin_allowed(callback, state):
        await callback.answer("دسترسی غیرمجاز.", show_alert=True)
        return
    parts = callback.data.split(":")
    if len(parts) < 4:
        await callback.answer("انتخاب چالش نامعتبر است.", show_alert=True)
        return
    action, value = parts[1], parts[3]
    data = await state.get_data()
    if value == "unchanged":
        value = data.get("challenge_mode", "limited")
    await state.update_data(
        challenge_mode=value,
        challenge_limit=(1 if value == "limited" else None),
    )
    current = await state.get_data()
    await callback.message.edit_text(
        "⚙️ <b>حالت چالش</b>\n\n"
        "حالت موردنظر را انتخاب کن؛ با انتخاب هر گزینه فقط حالت عوض می‌شود.\n"
        "بعد از انتخاب، روی «ادامه» بزن.",
        reply_markup=scenario_challenge_keyboard(
            action,
            bool(data.get("edit_id")),
            selected=current.get("challenge_mode", "limited"),
        ),
        parse_mode="HTML",
    )
    await callback.answer("حالت چالش تغییر کرد.")


@router.callback_query(lambda c: c.data.startswith("scenario_admin:") and ":challenge_next" in c.data)
async def scenario_form_challenge_next(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _scenario_admin_allowed(callback, state):
        await callback.answer("دسترسی غیرمجاز.", show_alert=True)
        return
    data = await state.get_data()
    await state.set_state(ScenarioAdminState.vote_threshold)
    await callback.message.edit_text(
        "قانون حدنصاب رای اول را وارد کنید:\n"
        "50 = حداقل ۵۰٪\n"
        "50+1 = در تعداد فرد، ۵۰٪ + ۱\n"
        "50-1 = در تعداد فرد، ۵۰٪ − ۱\n"
        "عدد = حدنصاب ثابت\n"
        "پیش‌فرض: 50"
    )
    await callback.answer()

@router.message(ScenarioAdminState.vote_threshold)
async def scenario_form_vote_threshold(message: Message, state: FSMContext) -> None:
    if message.chat.type != "private":
        return
    value = (message.text or "").strip().replace(" ", "")
    data = await state.get_data()
    if value == "-":
        value = str(data.get("current_vote_rule_input", "50"))
    if value in {"50", "half", "نصف"}:
        mode, threshold_value = "half_up", 0
        threshold = 2
    elif value in {"50+1", "half+1", "نصف+1"}:
        mode, threshold_value = "half_plus_one_odd", 0
        threshold = 2
    elif value in {"50-1", "half-1", "نصف-1"}:
        mode, threshold_value = "half_minus_one_odd", 0
        threshold = 2
    else:
        try:
            threshold = int(value)
            mode = "fixed"
            threshold_value = threshold
        except ValueError:
            await message.answer("قانون نامعتبر است. یکی از 50، 50+1، 50-1 یا یک عدد ثابت را وارد کنید.")
            return
    player_count = max(1, int(data.get("max_players") or 20))
    if mode == "fixed" and not 1 <= threshold <= player_count:
        await message.answer("حدنصاب ثابت باید بین ۱ تا تعداد بازیکنان سناریو باشد.")
        return
    try:
        current_rules = json.loads(data.get("current_voting_rules", "{}") or "{}")
    except (TypeError, ValueError):
        current_rules = {}
    rules = {
        "vote1_threshold_mode": mode,
        "vote1_threshold_value": threshold_value,
        "vote2_single_threshold_mode": current_rules.get("vote2_single_threshold_mode", "same_as_vote1"),
        "vote2_multi_resolution": current_rules.get("vote2_multi_resolution", "threshold"),
        "vote2_multi_threshold_mode": current_rules.get("vote2_multi_threshold_mode", "same_as_vote1"),
        "vote2_defenders_can_vote": bool(current_rules.get("vote2_defenders_can_vote", True)),
        "vote2_visibility": current_rules.get("vote2_visibility", "public"),
        "vote2_tie_policy": current_rules.get("vote2_tie_policy", "no_elimination"),
    }
    await state.update_data(vote_defense_threshold=(threshold if mode == "fixed" else 2), voting_rules=rules)
    await state.set_state(ScenarioAdminState.vote_rules)
    await message.answer(
        "قوانین رای دوم را در یک خط تنظیم کنید. قالب:\n"
        "چندمدافعی=threshold یا highest | مدافعان=بله یا خیر | مخفی=عمومی یا گرداننده یا ربات\n"
        "مثال: چندمدافعی=highest مدافعان=بله مخفی=عمومی\n"
        "برای بدون تغییر در ویرایش: -"
    )


@router.message(ScenarioAdminState.vote_rules)
async def scenario_form_vote_rules(message: Message, state: FSMContext) -> None:
    if message.chat.type != "private":
        return
    raw = (message.text or "").strip()
    data = await state.get_data()
    rules = dict(data.get("voting_rules") or {})
    if raw == "-" and data.get("edit_id"):
        try:
            rules = json.loads(data.get("current_voting_rules", "{}") or "{}") or rules
        except (TypeError, ValueError):
            pass
    elif raw != "-":
        normalized = raw.replace("،", " ").replace("|", " ")
        for token in normalized.split():
            if "=" not in token:
                continue
            key, value = token.split("=", 1)
            key = key.strip().lower()
            value = value.strip().lower()
            if key in {"چندمدافعی", "multi", "multi_resolution"}:
                rules["vote2_multi_resolution"] = "highest" if value in {"highest", "بیشترین"} else "threshold"
            elif key in {"مدافعان", "defenders"}:
                rules["vote2_defenders_can_vote"] = value in {"بله", "yes", "true", "1"}
            elif key in {"مخفی", "visibility"}:
                rules["vote2_visibility"] = {
                    "عمومی": "public", "public": "public",
                    "گرداننده": "host_private", "host": "host_private",
                    "ربات": "bot_private", "bot": "bot_private",
                }.get(value, rules.get("vote2_visibility", "public"))
            elif key in {"تساوی", "tie"}:
                rules["vote2_tie_policy"] = "random" if value in {"قرعه", "random"} else "no_elimination"
    await state.update_data(voting_rules=rules)
    await state.set_state(ScenarioAdminState.turn_time)
    await message.answer("⏱ زمان هر نوبت را فقط به‌صورت تعداد ثانیه وارد کن. مثال: 120\nپیش‌فرض: 120")
    return
    current = data.get("current_roles_text", "")
    prompt = (
        "🎭 نقش‌ها و سایدها را هر کدام در یک سطر وارد کنید.\n\n"
        "فرمت:\nپدرخوانده مافیا\nکنستانتین شهروند\nدکتر شهروند\nنوستراداموس مستقل\n\n"
        "کلمه آخر هر سطر ساید است و بقیه متن نام نقش.\n"
        "نقش تکراری را در سطر جداگانه بنویسید.\n"
        + ("\nترکیب فعلی:\n" + current if current else "")
        + ("\n\nبرای بدون تغییر، - بفرستید." if data.get("edit_id") else "")
    )
    await message.answer(prompt)

@router.message(ScenarioAdminState.roles)
async def scenario_form_roles_text(message: Message, state: FSMContext) -> None:
    if message.chat.type != "private":
        return
    value = (message.text or "").strip()
    data = await state.get_data()
    if value == "/cancel":
        await state.clear()
        await message.answer("لغو شد.", reply_markup=scenario_management_menu())
        return
    if value == "-" and data.get("edit_id"):
        value = data.get("current_roles_text", "")
    try:
        role_lines = _parse_scenario_roles(value)
    except ValueError as exc:
        await message.answer(str(exc) + "\nفرمت صحیح را رعایت کنید.")
        return
    if not role_lines:
        await message.answer("حداقل یک نقش وارد کنید.")
        return

    async with session_factory() as session:
        role_rows = list((await session.execute(select(Role))).scalars().all())
        role_map = {(r.name_fa.strip().casefold(), r.team): r for r in role_rows}
        resolved = []
        for role_name, team in role_lines:
            role = role_map.get((role_name.casefold(), team))
            if not role:
                role = Role(
                    key="custom_role_" + uuid4().hex[:16],
                    name_fa=role_name,
                    team=team,
                    description="",
                )
                session.add(role)
                await session.flush()
            resolved.append(role)
    await state.update_data(role_ids=[r.id for r in resolved])
    await state.set_state(ScenarioAdminState.challenge)
    await message.answer(
        "⚙️ قوانین سناریو را تنظیم کن. اول وضعیت چالش را انتخاب کن:",
        reply_markup=scenario_challenge_keyboard(data.get("mode", "create"), bool(data.get("edit_id"))),
    )


@router.callback_query(lambda c: c.data.startswith("scenario_admin:") and ":confirm" in c.data)
async def scenario_form_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _scenario_admin_allowed(callback, state):
        await callback.answer("دسترسی غیرمجاز.", show_alert=True)
        return
    data = await state.get_data()
    role_ids = [int(x) for x in data.get("role_ids", [])]
    if not role_ids:
        await callback.answer("حداقل یک نقش لازم است.", show_alert=True)
        return
    async with session_factory() as session:
        roles = []
        for rid in role_ids:
            role = await session.get(Role, rid)
            if role:
                roles.append(role)
        if not roles:
            await callback.answer("نقش‌ها پیدا نشدند.", show_alert=True)
            return
        edit_id = data.get("edit_id")
        if edit_id:
            scenario = await session.get(Scenario, int(edit_id))
            if not scenario:
                await callback.answer("سناریو پیدا نشد.", show_alert=True)
                return
            old = list((await session.execute(select(ScenarioRole).where(ScenarioRole.scenario_id == scenario.id))).scalars().all())
            for row in old:
                await session.delete(row)
        else:
            scenario = Scenario(
                key="custom_" + uuid4().hex[:12],
                name_fa=data["name"],
                description=data.get("description", ""),
                min_players=len(roles),
                max_players=len(roles),
                enabled=True,
                turn_seconds=int(data.get("turn_seconds", 120)),
                challenge_seconds=int(data.get("challenge_seconds", 60)),
                extra_challenge_seconds=int(data.get("extra_challenge_seconds", 60)),
                vote_defense_threshold=int(data.get("vote_defense_threshold", 2)),
                voting_rules=json.dumps(data.get("voting_rules", {}), ensure_ascii=False),
                challenge_mode=data.get("challenge_mode", "limited"),
                challenge_limit=1 if data.get("challenge_mode") == "limited" else None,
                training_url=data.get("training_url"),
            )
            session.add(scenario)
            await session.flush()
        scenario.name_fa = data["name"]
        scenario.description = data.get("description", "")
        scenario.min_players = len(roles)
        scenario.max_players = len(roles)
        scenario.turn_seconds = int(data.get("turn_seconds", 120))
        scenario.challenge_seconds = int(data.get("challenge_seconds", 60))
        scenario.extra_challenge_seconds = int(data.get("extra_challenge_seconds", 60))
        scenario.challenge_mode = data.get("challenge_mode", "limited")
        scenario.challenge_limit = 1 if scenario.challenge_mode == "limited" else None
        scenario.vote_defense_threshold = int(data.get("vote_defense_threshold", 2))
        scenario.voting_rules = json.dumps(data.get("voting_rules", {}), ensure_ascii=False)
        if data.get("training_url") is not None:
            scenario.training_url = data.get("training_url")
        for pos, role in enumerate(roles):
            session.add(ScenarioRole(scenario_id=scenario.id, role_id=role.id, count=1, position=pos))
        await session.commit()
        count = len(roles)
    group_id = data.get("group_scenario_group_id")
    await state.clear()
    async with session_factory() as session:
        markup = await _scenario_management_markup(session, group_id)
    await callback.message.edit_text(
        f"✅ سناریو «{data['name']}» ذخیره شد.\n\n👥 تعداد نفرات: {count}\n"
        f"🤏 چالش: {data.get('challenge_mode', 'limited')}\n"
        f"⏱ نوبت: {_format_duration(int(data.get('turn_seconds', 120)))}",
        reply_markup=markup,
    )
    await callback.answer("سناریو ذخیره شد.")


@router.callback_query(lambda c: c.data.startswith("scenario_admin:") and ":back" in c.data)
async def scenario_form_back_to_roles(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _scenario_admin_allowed(callback, state):
        await callback.answer("دسترسی غیرمجاز.", show_alert=True)
        return
    await state.set_state(ScenarioAdminState.roles)
    await callback.message.edit_text("🎭 نقش‌ها و سایدها را دوباره ارسال کن.")
    await callback.answer()


@router.callback_query(lambda c: c.data == "scenario_admin:training" or c.data.startswith("scenario_admin:training:"))
async def scenario_training_manage_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _scenario_admin_allowed(callback, state):
        await callback.answer("دسترسی فقط برای مدیر ربات است.", show_alert=True)
        return
    async with session_factory() as session:
        scenarios = list((await session.execute(
            select(Scenario).where(Scenario.key != "classic").order_by(Scenario.id)
        )).scalars().all())
    await callback.message.edit_text(
        "📚 سناریویی را انتخاب کن تا لینک آموزش آن را ثبت یا ویرایش کنیم:",
        reply_markup=scenario_admin_list_keyboard(scenarios, "training_select"),
    )
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("scenario_admin:training_select:"))
async def scenario_training_select(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _scenario_admin_allowed(callback, state):
        await callback.answer("دسترسی غیرمجاز.", show_alert=True)
        return
    parts = callback.data.split(":")
    sid = int(parts[2])
    callback_group_id = int(parts[3]) if len(parts) > 3 else None
    async with session_factory() as session:
        scenario = await session.get(Scenario, sid)
    if not scenario:
        await callback.answer("سناریو پیدا نشد.", show_alert=True)
        return
    previous = await state.get_data()
    await state.clear()
    await state.update_data(scenario_id=sid, group_scenario_group_id=callback_group_id or previous.get("group_scenario_group_id"))
    await state.set_state(ScenarioTrainingState.input)
    current = scenario.training_url or "ثبت نشده"
    await callback.message.edit_text(
        f"📚 آموزش سناریوی «{escape(scenario.name_fa)}»\n\n"
        f"لینک فعلی: {escape(current)}\n\n"
        "لینک آموزش را ارسال کن. باید با http:// یا https:// شروع شود.\n"
        "برای حذف لینک: -\nبرای لغو: /cancel",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(ScenarioTrainingState.input)
async def scenario_training_save(message: Message, state: FSMContext) -> None:
    if message.chat.type != "private" or not message.from_user:
        return
    raw = (message.text or "").strip()
    data = await state.get_data()
    group_id = data.get("group_scenario_group_id")
    allowed = bool(message.from_user.id in get_settings().admin_id_set)
    if not allowed and group_id:
        async with session_factory() as auth_session:
            auth_group = await auth_session.get(Group, int(group_id))
            allowed = bool(auth_group and await _is_group_admin(message.bot, auth_group, message.from_user.id))
    if not allowed:
        return
    sid = int(data.get("scenario_id", 0) or 0)
    if raw == "/cancel":
        group_id = data.get("group_scenario_group_id")
        await state.clear()
        async with session_factory() as session:
            markup = await _scenario_management_markup(session, group_id)
        await message.answer("❌ ثبت لینک آموزش لغو شد.", reply_markup=markup)
        return
    if raw == "-":
        url = None
    elif re.match(r"^https?://\S+$", raw, re.IGNORECASE):
        url = raw
    else:
        await message.answer("❌ لینک معتبر نیست. لینک باید با http:// یا https:// شروع شود.")
        return
    async with session_factory() as session:
        scenario = await session.get(Scenario, sid)
        if not scenario or scenario.key == "classic":
            await state.clear()
            await message.answer("❌ سناریو پیدا نشد.", reply_markup=scenario_management_menu())
            return
        scenario.training_url = url
        await session.commit()
        name = scenario.name_fa
    group_id = data.get("group_scenario_group_id")
    await state.clear()
    async with session_factory() as session:
        markup = await _scenario_management_markup(session, group_id)
    await message.answer(
        f"✅ لینک آموزش سناریوی «{escape(name)}» {'حذف شد' if not url else 'ذخیره شد'}.",
        reply_markup=markup,
        parse_mode="HTML",
    )


@router.callback_query(lambda c: c.data == "scenario_admin:roles" or c.data.startswith("scenario_admin:roles:"))
async def scenario_roles_manage_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _scenario_admin_allowed(callback, state):
        await callback.answer("دسترسی فقط برای مدیر ربات است.", show_alert=True)
        return
    async with session_factory() as session:
        scenarios = list((await session.execute(
            select(Scenario).where(Scenario.key != "classic").order_by(Scenario.id)
        )).scalars().all())
    await callback.message.edit_text("🎭 سناریویی را انتخاب کن تا نقش‌ها و توضیحاتش را مدیریت کنیم:", reply_markup=scenario_admin_list_keyboard(scenarios, "role_list", await _scenario_context_group_id(callback, state)))
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("scenario_admin:role_list:"))
async def scenario_role_list(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _scenario_admin_allowed(callback, state):
        await callback.answer("دسترسی غیرمجاز.", show_alert=True)
        return
    parts = callback.data.split(":")
    sid = int(parts[2])
    callback_group_id = int(parts[3]) if len(parts) > 3 else None
    async with session_factory() as session:
        scenario = await session.get(Scenario, sid)
        if not scenario:
            await callback.answer("سناریو پیدا نشد.", show_alert=True)
            return
        rows = list((await session.execute(
            select(ScenarioRole, Role)
            .join(Role, Role.id == ScenarioRole.role_id)
            .where(ScenarioRole.scenario_id == sid)
            .order_by(ScenarioRole.position, Role.name_fa)
        )).all())
        roles = [role for _, role in rows]
    previous = await state.get_data()
    group_id = callback_group_id or previous.get("group_scenario_group_id")
    await state.clear()
    await state.update_data(group_scenario_group_id=group_id)
    await callback.message.edit_text(
        f"🎭 نقش‌های سناریوی «{scenario.name_fa}»\n\n"
        "برای ثبت چند توضیح همزمان، از «📝 ثبت توضیحات یکجا» استفاده کن. فرمت هر سطر: نقش/توضیحات",
        reply_markup=scenario_role_description_list_keyboard(roles, sid, group_id),
    )
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("scenario_admin:role_desc_batch:"))
async def scenario_role_description_batch_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _scenario_admin_allowed(callback, state):
        await callback.answer("دسترسی غیرمجاز.", show_alert=True)
        return
    parts = callback.data.split(":")
    sid = int(parts[2])
    callback_group_id = int(parts[3]) if len(parts) > 3 else None
    async with session_factory() as session:
        scenario = await session.get(Scenario, sid)
        rows = list((await session.execute(
            select(ScenarioRole, Role)
            .join(Role, Role.id == ScenarioRole.role_id)
            .where(ScenarioRole.scenario_id == sid)
            .order_by(ScenarioRole.position, Role.name_fa)
        )).all()) if scenario else []
    if not scenario:
        await callback.answer("سناریو پیدا نشد.", show_alert=True)
        return
    previous = await state.get_data()
    group_scenario_group_id = callback_group_id or previous.get("group_scenario_group_id")
    await state.clear()
    await state.update_data(
        scenario_id=sid,
        group_scenario_group_id=group_scenario_group_id,
        batch_mode=True,
        sequence_mode=False,
        sequence_role_ids=[],
        sequence_index=0,
        pending_descriptions={},
    )
    await state.set_state(RoleDescriptionState.input)
    names = "\n".join(f"• {escape(role.name_fa)}" for _, role in rows)
    await callback.message.edit_text(
        f"📝 توضیحات نقش‌های «{escape(scenario.name_fa)}»\n\n"
        "هر نقش را در یک سطر بفرست:\n"
        "<code>نقش/توضیحات</code>\n\n"
        "می‌توانی چند سطر را همزمان ارسال کنی.\n\n"
        f"نقش‌های این سناریو:\n{names}\n\n"
        "برای لغو: /cancel",
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("scenario_admin:role_desc_sequence:"))
async def scenario_role_description_sequence_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _scenario_admin_allowed(callback, state):
        await callback.answer("دسترسی غیرمجاز.", show_alert=True)
        return
    parts = callback.data.split(":")
    sid = int(parts[2])
    callback_group_id = int(parts[3]) if len(parts) > 3 else None
    async with session_factory() as session:
        scenario = await session.get(Scenario, sid)
        rows = list((await session.execute(
            select(ScenarioRole, Role)
            .join(Role, Role.id == ScenarioRole.role_id)
            .where(ScenarioRole.scenario_id == sid)
            .order_by(ScenarioRole.position, ScenarioRole.id)
        )).all())
    if not scenario or not rows:
        await callback.answer("برای این سناریو نقشی ثبت نشده است.", show_alert=True)
        return
    role_ids = []
    seen = set()
    for _scenario_role, role in rows:
        if role.id not in seen:
            role_ids.append(role.id)
            seen.add(role.id)
    previous = await state.get_data()
    await state.update_data(
        scenario_id=sid,
        group_scenario_group_id=callback_group_id or previous.get("group_scenario_group_id"),
        sequence_role_ids=role_ids,
        sequence_index=0,
        sequence_mode=True,
        batch_mode=False,
        pending_descriptions={},
    )
    await state.set_state(RoleDescriptionState.input)
    first_role = next(role for _row, role in rows if role.id == role_ids[0])
    await callback.message.edit_text(
        f"📨 <b>ثبت ترتیبی توضیحات نقش‌ها</b>\n\n"
        f"نقش ۱ از {len(role_ids)}: <b>{escape(first_role.name_fa)}</b>\n\n"
        "حالا توضیح این نقش را بفرست یا یک پیام حاوی توضیحات را Forward کن.\n"
        "چندخطی بودن توضیحات کاملاً مجاز است.\n\n"
        "برای انصراف: /cancel",
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("scenario_admin:role_desc:"))
async def scenario_role_description_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _scenario_admin_allowed(callback, state):
        await callback.answer("دسترسی غیرمجاز.", show_alert=True)
        return
    parts = callback.data.split(":")
    sid, rid = int(parts[2]), int(parts[3])
    callback_group_id = int(parts[4]) if len(parts) > 4 else None
    if callback_group_id:
        await state.update_data(group_scenario_group_id=callback_group_id)
    async with session_factory() as session:
        scenario = await session.get(Scenario, int(sid))
        role = await session.get(Role, int(rid))
    if not scenario or not role:
        await callback.answer("سناریو یا نقش پیدا نشد.", show_alert=True)
        return
    await state.update_data(
        scenario_id=int(sid),
        role_id=int(rid),
        sequence_mode=False,
        batch_mode=False,
        sequence_role_ids=[],
        sequence_index=0,
        pending_descriptions={},
    )
    await state.set_state(RoleDescriptionState.input)
    await callback.message.edit_text(
        f"📝 توضیحات نقش «{escape(role.name_fa)}» را بفرست.\n\n"
        "می‌توانی متن چندخطی ارسال کنی یا یک پیام حاوی توضیحات را Forward کنی.\n\n"
        f"توضیح فعلی: {escape(role.description or 'ثبت نشده')}",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(RoleDescriptionState.input)
async def scenario_role_description_save(message: Message, state: FSMContext) -> None:
    if message.chat.type != "private" or not message.from_user:
        return
    raw = (message.text or message.caption or "").strip()
    if raw == "/cancel":
        await state.clear()
        await message.answer("لغو شد.", reply_markup=scenario_management_menu())
        return
    if not raw:
        await message.answer(
            "❌ توضیحات خالی است. متن را ارسال کن یا پیام دارای توضیحات را Forward کن."
        )
        return
    data = await state.get_data()
    sid = int(data.get("scenario_id", 0) or 0)

    # Sequential mode: save one role and immediately move to the next role.
    if data.get("sequence_mode"):
        role_ids = [int(x) for x in data.get("sequence_role_ids", [])]
        index = int(data.get("sequence_index", 0) or 0)
        if not sid or not role_ids or index >= len(role_ids):
            await state.clear()
            await message.answer("اطلاعات ثبت توضیحات ناقص است.", reply_markup=scenario_management_menu())
            return
        role_id = role_ids[index]
        async with session_factory() as session:
            scenario = await session.get(Scenario, sid)
            role = await session.get(Role, role_id)
            if not scenario or not role:
                await state.clear()
                await message.answer("سناریو یا نقش پیدا نشد.", reply_markup=scenario_management_menu())
                return
            current_name = role.name_fa
            pending = dict(data.get("pending_descriptions") or {})
            pending[str(role_id)] = raw
            next_role = None
            if index + 1 < len(role_ids):
                next_role = await session.get(Role, role_ids[index + 1])
        if next_role:
            await state.update_data(sequence_index=index + 1, pending_descriptions=pending)
            await message.answer(
                f"✅ توضیحات «{escape(current_name)}» آماده شد.\n\n"
                f"نقش {index + 2} از {len(role_ids)}: <b>{escape(next_role.name_fa)}</b>\n\n"
                "توضیحات را ارسال یا پیام توضیحات را Forward کن.",
                parse_mode="HTML",
            )
            return

        await state.update_data(pending_descriptions=pending)
        await state.set_state(RoleDescriptionState.sequence)
        builder = InlineKeyboardBuilder()
        builder.row(
            InlineKeyboardButton(
                text="✅ تأیید نهایی",
                callback_data=f"scenario_admin:role_desc_sequence_confirm:{sid}",
            )
        )
        builder.row(
            InlineKeyboardButton(
                text="🎭 بازگشت به فهرست نقش‌ها",
                callback_data=f"scenario_admin:role_list:{sid}",
            )
        )
        await message.answer(
            f"✅ توضیحات همه {len(role_ids)} نقش آماده شد.\n\n"
            "اگر اطلاعات درست است «تأیید نهایی» را بزن.",
            reply_markup=builder.as_markup(),
        )
        return

    if data.get("batch_mode"):
        role_lines = [line.strip() for line in raw.splitlines() if line.strip()]
        if not role_lines:
            await message.answer("حداقل یک سطر نقش/توضیح وارد کن.")
            return
        pending = {}
        async with session_factory() as session:
            scenario = await session.get(Scenario, sid)
            rows = list((await session.execute(
                select(ScenarioRole, Role)
                .join(Role, Role.id == ScenarioRole.role_id)
                .where(ScenarioRole.scenario_id == sid)
                .order_by(ScenarioRole.position, ScenarioRole.id)
            )).all()) if scenario else []
            role_map = {role.name_fa.strip().casefold(): role for _, role in rows}
            for line in role_lines:
                if "/" not in line:
                    await message.answer(f"❌ فرمت سطر نادرست است: {line}\nفرمت: نقش/توضیحات")
                    return
                name, description = line.split("/", 1)
                role = role_map.get(name.strip().casefold())
                if not role:
                    await message.answer(f"❌ نقش «{name.strip()}» در این سناریو پیدا نشد.")
                    return
                description = description.strip()
                if not description:
                    await message.answer(f"❌ توضیحات «{role.name_fa}» خالی است.")
                    return
                pending[str(role.id)] = description
        await state.update_data(pending_descriptions=pending)
        await state.set_state(RoleDescriptionState.sequence)
        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(
            text="✅ تأیید نهایی",
            callback_data=f"scenario_admin:role_desc_sequence_confirm:{sid}",
        ))
        builder.row(InlineKeyboardButton(
            text="🎭 بازگشت به فهرست نقش‌ها",
            callback_data=f"scenario_admin:role_list:{sid}",
        ))
        await message.answer(
            f"📋 {len(pending)} توضیح آماده ذخیره است. برای ثبت نهایی تأیید کن.",
            reply_markup=builder.as_markup(),
        )
        return

    role_id = int(data.get("role_id", 0) or 0)
    if not sid or not role_id:
        await state.clear()
        await message.answer("اطلاعات نقش ناقص است.", reply_markup=scenario_management_menu())
        return
    async with session_factory() as session:
        scenario = await session.get(Scenario, sid)
        role = await session.get(Role, role_id)
        if not scenario or not role:
            await state.clear()
            await message.answer("سناریو یا نقش پیدا نشد.", reply_markup=scenario_management_menu())
            return
        role.description = raw
        await session.commit()
        roles = list((await session.execute(
            select(ScenarioRole, Role)
            .join(Role, Role.id == ScenarioRole.role_id)
            .where(ScenarioRole.scenario_id == sid)
            .order_by(ScenarioRole.position, Role.name_fa)
        )).all())
    await state.clear()
    await message.answer(
        f"✅ توضیحات «{escape(role.name_fa)}» ذخیره شد.",
        reply_markup=scenario_role_description_list_keyboard(
            [role for _scenario_role, role in roles], sid
        ),
        parse_mode="HTML",
    )


@router.callback_query(lambda c: c.data.startswith("scenario_admin:role_desc_sequence_confirm:"))
async def scenario_role_description_sequence_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _scenario_admin_allowed(callback, state):
        await callback.answer("دسترسی غیرمجاز.", show_alert=True)
        return
    sid = int(callback.data.rsplit(":", 1)[1])
    data = await state.get_data()
    pending = {
        int(role_id): str(description)
        for role_id, description in (data.get("pending_descriptions") or {}).items()
    }
    if not pending:
        await callback.answer("توضیح جدیدی برای ذخیره وجود ندارد.", show_alert=True)
        return
    async with session_factory() as session:
        scenario = await session.get(Scenario, sid)
        if not scenario:
            await callback.answer("سناریو پیدا نشد.", show_alert=True)
            return
        for role_id, description in pending.items():
            role = await session.get(Role, role_id)
            if role:
                role.description = description
        await session.commit()
        rows = list((await session.execute(
            select(ScenarioRole, Role)
            .join(Role, Role.id == ScenarioRole.role_id)
            .where(ScenarioRole.scenario_id == sid)
            .order_by(ScenarioRole.position, Role.name_fa)
        )).all())
    await state.clear()
    await callback.message.edit_text(
        f"🎭 <b>توضیحات نقش‌های «{escape(scenario.name_fa)}»</b>\n\n"
        f"✅ توضیحات {len(pending)} نقش ذخیره شد.",
        reply_markup=scenario_role_description_list_keyboard(
            [role for _scenario_role, role in rows], sid
        ),
        parse_mode="HTML",
    )
    await callback.answer("توضیحات تأیید و ذخیره شد.")


@router.callback_query(lambda c: c.data.startswith("scenario_admin:edit:"))
async def scenario_edit_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _scenario_admin_allowed(callback, state):
        await callback.answer("دسترسی غیرمجاز.", show_alert=True)
        return
    parts = callback.data.split(":")
    sid = int(parts[2])
    callback_group_id = int(parts[3]) if len(parts) > 3 else None
    async with session_factory() as session:
        scenario = await session.get(Scenario, sid)
        if not scenario:
            await callback.answer("سناریو پیدا نشد.", show_alert=True)
            return
        current_roles_text = await _scenario_roles_text(session, sid)
    context = await state.get_data()
    group_scenario_group_id = callback_group_id or context.get("group_scenario_group_id")
    await state.clear()
    await state.set_state(ScenarioAdminState.name)
    await state.update_data(
        mode="edit",
        group_scenario_group_id=group_scenario_group_id,
        edit_id=sid,
        current_name=scenario.name_fa,
        current_description=scenario.description,
        current_turn_seconds=getattr(scenario, "turn_seconds", 120),
        current_challenge_seconds=getattr(scenario, "challenge_seconds", 60),
        current_extra_challenge_seconds=getattr(scenario, "extra_challenge_seconds", 60),
        current_roles_text=current_roles_text,
        current_voting_rules=getattr(scenario, "voting_rules", "{}"),
        current_vote_rule_input="50",
        training_url=getattr(scenario, "training_url", None),
        max_players=scenario.max_players,
        min_players=scenario.min_players,
        challenge_mode=scenario.challenge_mode,
        current_vote_defense_threshold=getattr(scenario, "vote_defense_threshold", 2),
    )
    await callback.message.edit_text(f"✏️ ویرایش «{scenario.name_fa}»\n\nنام جدید را ارسال کنید یا - برای بدون تغییر:")
    await callback.answer()

@router.callback_query(lambda c: c.data.startswith("scenario_admin:delete:"))
async def scenario_delete_confirm_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _scenario_admin_allowed(callback, state):
        await callback.answer("دسترسی غیرمجاز.", show_alert=True)
        return
    parts = callback.data.split(":")
    sid = int(parts[2])
    callback_group_id = int(parts[3]) if len(parts) > 3 else None
    if callback_group_id:
        await state.update_data(group_scenario_group_id=callback_group_id)
    async with session_factory() as session:
        scenario = await session.get(Scenario, sid)
    if not scenario:
        await callback.answer("سناریو پیدا نشد.", show_alert=True)
        return
    await callback.message.edit_text(
        f"⚠️ حذف سناریو «{scenario.name_fa}»\n\nترکیب نقش‌های آن نیز حذف می‌شود. ادامه می‌دهید؟",
        reply_markup=scenario_delete_confirm_keyboard(sid, callback_group_id or (await state.get_data()).get("group_scenario_group_id")),
    )
    await callback.answer()

@router.callback_query(lambda c: c.data.startswith("scenario_admin:delete_confirm:"))
async def scenario_delete_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _scenario_admin_allowed(callback, state):
        await callback.answer("دسترسی غیرمجاز.", show_alert=True)
        return
    parts = callback.data.split(":")
    sid = int(parts[2])
    callback_group_id = int(parts[3]) if len(parts) > 3 else None
    if callback_group_id:
        await state.update_data(group_scenario_group_id=callback_group_id)
    async with session_factory() as session:
        scenario = await session.get(Scenario, sid)
        if not scenario:
            await callback.answer("سناریو پیدا نشد.", show_alert=True)
            return
        active = await session.scalar(
            select(Game.id).where(
                Game.scenario_id == sid,
                Game.status.in_(["waiting", "draft", "running"]),
            ).limit(1)
        )
        if active:
            await callback.answer("این سناریو در یک بازی فعال استفاده می‌شود و فعلاً قابل حذف نیست.", show_alert=True)
            return
        history = await session.scalar(select(Game.id).where(Game.scenario_id == sid).limit(1))
        if history:
            scenario.enabled = False
            await session.commit()
            result_text = "🗑 سناریو از فهرست فعال حذف شد؛ چون سابقه بازی دارد، برای حفظ تاریخچه به‌صورت غیرفعال نگه داشته شد."
        else:
            await session.delete(scenario)
            await session.commit()
            result_text = "🗑 سناریو حذف شد."
    group_id = (await state.get_data()).get("group_scenario_group_id")
    await state.clear()
    if group_id:
        async with session_factory() as session:
            scenarios = list((await session.execute(select(Scenario).where(Scenario.enabled.is_(True), Scenario.key != "classic").order_by(Scenario.id))).scalars().all())
        await callback.message.edit_text(result_text, reply_markup=group_scenario_management_menu(int(group_id), scenarios))
    else:
        await callback.message.edit_text(result_text, reply_markup=scenario_management_menu())
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("notify:toggle:"))
async def notification_toggle(callback: CallbackQuery) -> None:
    if not callback.from_user or not callback.message:
        return
    field = callback.data.split(":")[-1]
    allowed = {"notify_game_result","notify_achievements","notify_rank_changes","notify_challenges","notify_turns"}
    if field not in allowed:
        await callback.answer("گزینه نامعتبر است.", show_alert=True)
        return
    async with session_factory() as session:
        user = (await session.execute(select(User).where(User.telegram_id == callback.from_user.id))).scalar_one_or_none()
        if not user:
            await callback.answer("کاربر پیدا نشد.", show_alert=True)
            return
        setattr(user, field, not getattr(user, field))
        await session.commit()
        await callback.message.edit_reply_markup(reply_markup=notification_settings_menu(user))
    await callback.answer("ذخیره شد.")


# Tournament management
def _tour_date(raw):
    try:
        y,m,d=[int(x) for x in raw.strip().replace('-', '/').split('/')[:3]]
        if y >= 1700:
            return datetime(y,m,d,12,tzinfo=ZoneInfo('Asia/Tehran'))
        # Persian date: find the exact Gregorian date through the bot's
        # canonical Gregorian -> Jalali converter.
        from datetime import timedelta
        from app.services.game import gregorian_to_jalali
        cursor=datetime(y+621,1,1)
        for offset in range(0, 400):
            day=cursor+timedelta(days=offset)
            if gregorian_to_jalali(day.year,day.month,day.day)==(y,m,d):
                return day.replace(hour=12,tzinfo=ZoneInfo('Asia/Tehran'))
        return None
    except (ValueError, TypeError):
        return None
def _tour_prizes(raw):
    out=[]
    for line in raw.replace('،', '\n').replace(',', '\n').splitlines():
        if line.strip(): out.append(int(line.strip()))
    if not out: raise ValueError
    if any(x < 0 for x in out): raise ValueError
    return out

async def _tour_users(session, names, bot=None, group=None):
    """Resolve tournament players robustly within the selected Telegram group."""
    def _normalize_digits(value: str) -> str:
        return str(value or "").translate(str.maketrans(
            "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
            "01234567890123456789",
        ))

    def _clean(value: str) -> str:
        value = _normalize_digits(str(value or "").strip())
        value = re.sub(r"^\s*\d+\s*[.)-]?\s+", "", value).strip()
        return value.lstrip("@").strip()

    users=list((await session.execute(select(User))).scalars().all())
    result=[]
    seen=set()
    unresolved=[]

    async def _add_telegram_user(tg_user):
        if not tg_user:
            return None
        existing=next((u for u in users if int(u.telegram_id or 0)==int(tg_user.id)), None)
        if existing:
            return existing
        synced=await sync_telegram_user(
            session,
            tg_user.id,
            tg_user.username,
            tg_user.first_name or "",
            tg_user.last_name,
        )
        users.append(synced)
        return synced

    async def _group_member_by_username(username):
        if not bot or not group or not username:
            return None
        # Telegram Bot API has no direct "find member by username" method.
        # When the account is not locally synced, resolve it from the group
        # member list if Telegram exposes the member in the group.
        try:
            admins=await bot.get_chat_administrators(group.telegram_id)
            for admin in admins:
                if (admin.user.username or "").casefold()==username.casefold():
                    return admin.user
        except Exception:
            pass
        return None

    for raw in names:
        n=_clean(raw)
        if not n:
            continue

        matches=[]
        uid_text=_normalize_digits(n)
        if uid_text.isdigit():
            uid=int(uid_text)
            matches=[u for u in users if int(u.telegram_id or 0)==uid]
            if not matches and bot and group:
                try:
                    member=await bot.get_chat_member(group.telegram_id, uid)
                    synced=await _add_telegram_user(member.user)
                    matches=[synced] if synced else []
                except Exception:
                    matches=[]
        else:
            key=n.casefold()
            exact=[]
            for u in users:
                values={
                    str(u.display_name or "").strip(),
                    str(u.name_base or "").strip(),
                    str(u.first_name or "").strip(),
                    str(u.username or "").strip().lstrip("@"),
                    str(u.last_name or "").strip(),
                }
                if any(v and v.casefold()==key for v in values):
                    exact.append(u)
            matches=exact

            # If username is not locally synced, try Telegram group admins.
            if not matches:
                tg_user=await _group_member_by_username(n)
                if tg_user:
                    synced=await _add_telegram_user(tg_user)
                    matches=[synced] if synced else []

            if not matches:
                partial=[]
                for u in users:
                    values=[
                        str(u.display_name or "").strip(),
                        str(u.name_base or "").strip(),
                        str(u.first_name or "").strip(),
                        str(u.username or "").strip().lstrip("@"),
                        str(u.last_name or "").strip(),
                    ]
                    if any(key and key in v.casefold() for v in values if v):
                        partial.append(u)
                if len(partial)==1:
                    matches=partial

        if len(matches)==1 and matches[0].id not in seen:
            result.append(matches[0])
            seen.add(matches[0].id)
        elif not matches:
            unresolved.append(str(raw).strip())

    return result, unresolved

async def _tour_allowed(session, bot, user_id, tid):
    t=await session.get(Tournament,tid)
    return t if t and await _selected_group(session,bot,user_id,t.group_id) else None

@router.callback_query(lambda c: c.data == 'groupmgmt:tournaments')
async def tournament_group_entry(callback: CallbackQuery):
    async with session_factory() as session: groups=await _manageable_groups(session,callback.bot,callback.from_user.id)
    if len(groups)==1: await callback.message.edit_text('🏆 مدیریت تورنمنت‌ها',reply_markup=tournament_admin_menu(groups[0].id))
    elif groups: await callback.message.edit_text('گروه را انتخاب کن:',reply_markup=group_list_keyboard(groups,'tournaments','menu:group_management'))
    else: await callback.message.edit_text('هیچ گروه قابل مدیریتی پیدا نشد.',reply_markup=group_management_menu())
    await callback.answer()

@router.callback_query(lambda c: c.data.startswith('groupmgmt:select:tournaments:'))
async def tournament_group_selected(callback: CallbackQuery):
    gid=int(callback.data.rsplit(':',1)[1])
    async with session_factory() as session: ok=await _selected_group(session,callback.bot,callback.from_user.id,gid)
    if not ok: await callback.answer('دسترسی ندارید.',show_alert=True); return
    await callback.message.edit_text('🏆 مدیریت تورنمنت‌ها',reply_markup=tournament_admin_menu(gid)); await callback.answer()

@router.callback_query(lambda c: c.data.startswith('tournament:list:'))
async def tournament_list(callback: CallbackQuery):
    gid=int(callback.data.rsplit(':',1)[1])
    async with session_factory() as session:
        if not await _selected_group(session,callback.bot,callback.from_user.id,gid): await callback.answer('دسترسی ندارید.',show_alert=True); return
        ts=list((await session.execute(select(Tournament).where(Tournament.group_id==gid).order_by(Tournament.start_at.desc()))).scalars().all())
    b=InlineKeyboardBuilder()
    for t in ts: b.row(InlineKeyboardButton(text=f'{t.emoji} {t.name[:50]}',callback_data=f'tournament:open:{t.id}'))
    b.row(InlineKeyboardButton(text='➕ افزودن تورنمنت',callback_data=f'tournament:add:{gid}'))
    b.row(InlineKeyboardButton(text='↩️ بازگشت',callback_data='groupmgmt:tournaments'))
    await callback.message.edit_text('🗂 تورنمنت‌های گروه:',reply_markup=b.as_markup()); await callback.answer()

@router.callback_query(lambda c: c.data.startswith('tournament:add:'))
async def tournament_add_start(callback: CallbackQuery,state:FSMContext):
    gid=int(callback.data.rsplit(':',1)[1])
    async with session_factory() as session:
        if not await _selected_group(session,callback.bot,callback.from_user.id,gid): await callback.answer('دسترسی ندارید.',show_alert=True); return
    # Set the FSM state before writing draft data. This avoids a short window where
    # the prompt is visible but the state storage has not yet been committed.
    await state.clear()
    await state.set_state(TournamentState.input)
    await state.update_data(action='add', group_id=gid, step='name')
    # Send a fresh prompt instead of editing the management menu. The user's
    # next message is therefore unambiguously the tournament draft input.
    await callback.message.answer('➕ نام تورنمنت را بفرست.', reply_markup=ForceReply(selective=True))
    await callback.answer()

@router.message(TournamentState.input)
async def tournament_input(message: Message,state:FSMContext):
    if not message.from_user or not message.text:
        return

    value=message.text.strip()
    data=await state.get_data()
    action=data.get('action')
    if not action:
        await state.clear()
        return

    if value=='/cancel': await state.clear(); await message.answer('لغو شد.',reply_markup=tournament_admin_menu(int(data.get('group_id',0)))); return
    if data.get('action')=='add':
        step=data.get('step')
        if step=='name': await state.update_data(name=value,step='emoji'); await message.answer('🎨 اموجی تورنمنت را بفرست.', reply_markup=ForceReply(selective=True)); return
        if step=='emoji': await state.update_data(emoji=value[:20],step='date'); await message.answer('📅 تاریخ شروع را بفرست (YYYY/MM/DD).', reply_markup=ForceReply(selective=True)); return
        if step=='date':
            dt=_tour_date(value)
            if not dt: await message.answer('تاریخ معتبر نیست.'); return
            await state.update_data(start_at=dt.isoformat(),step='prizes'); await message.answer('🏅 امتیاز رتبه‌ها را هر رتبه در یک خط بفرست:\n300\n200\n100\n50', reply_markup=ForceReply(selective=True)); return
        if step=='prizes':
            try: prizes=_tour_prizes(value)
            except ValueError: await message.answer('امتیازها باید عددهای مثبت باشند.'); return
            await state.update_data(prizes='\n'.join(map(str,prizes)),step='description'); await message.answer('📝 توضیحات را بفرست؛ برای بدون توضیح -', reply_markup=ForceReply(selective=True)); return
        if step=='description':
            async with session_factory() as session:
                group=await _selected_group(session,message.bot,message.from_user.id,int(data['group_id']))
                user=await session.scalar(select(User).where(User.telegram_id==message.from_user.id))
                if not group or not user: await state.clear(); await message.answer('دسترسی ندارید.'); return
                session.add(Tournament(group_id=group.id,name=data['name'],emoji=data['emoji'],start_at=datetime.fromisoformat(data['start_at']),prize_points=data['prizes'],description='' if value=='-' else value,created_by_user_id=user.id)); await session.commit()
            await state.clear(); await message.answer('✅ تورنمنت ساخته شد.',reply_markup=tournament_admin_menu(int(data['group_id']))); return
    tid=int(data['tid'])
    async with session_factory() as session:
        t=await session.get(Tournament,tid)
        if t and data.get('action')=='edit':
            step=data.get('step')
            if step=='name':
                await state.update_data(step='emoji',name=value if value!='-' else t.name)
                await message.answer('🎨 اموجی جدید را بفرست؛ برای حفظ اموجی فعلی -')
                return
            if step=='emoji':
                await state.update_data(step='date',emoji=value if value!='-' else t.emoji)
                await message.answer('📅 تاریخ شروع جدید را بفرست؛ برای حفظ تاریخ فعلی -')
                return
            if step=='date':
                dt=_tour_date(value)
                if value=='-': dt=t.start_at
                if not dt: await message.answer('تاریخ معتبر نیست.'); return
                await state.update_data(step='prizes',start_at=dt.isoformat())
                await message.answer('🏅 امتیاز رتبه‌ها را هر رتبه در یک خط بفرست؛ برای حفظ فعلی -')
                return
            if step=='prizes':
                prizes=t.prize_points
                if value!='-':
                    try: prizes='\\n'.join(map(str,_tour_prizes(value)))
                    except ValueError: await message.answer('امتیازها نامعتبر است.'); return
                await state.update_data(step='description',prizes=prizes)
                await message.answer('📝 توضیحات جدید را بفرست؛ برای حفظ فعلی -')
                return
            if step=='description':
                t.name=data['name']; t.emoji=data['emoji']; t.start_at=datetime.fromisoformat(data['start_at']); t.prize_points=data['prizes']
                if value!='-': t.description=value
                await session.commit(); await state.clear(); await message.answer('✅ تورنمنت ویرایش شد.',reply_markup=tournament_manage_menu(tid,t.group_id)); return
        if t and data.get('action') in {'rename_group','group_add','group_remove'}:
            g=await session.get(TournamentGroup,int(data['group_id_no']))
            if not g: await state.clear(); await message.answer('گروه پیدا نشد.'); return
            if data['action']=='rename_group':
                g.name=value
            else:
                users=await _tour_users(session,[value])
                if not users: await message.answer(f'بازیکن پیدا نشد: {unresolved[0] if unresolved else value}'); return
                tp=await session.scalar(select(TournamentPlayer).where(TournamentPlayer.tournament_id==tid,TournamentPlayer.user_id==users[0].id))
                if not tp: await message.answer('این بازیکن در تورنمنت ثبت نشده.'); return
                tp.group_no=g.group_no if data['action']=='group_add' else None
            await session.commit(); await state.clear(); await message.answer('✅ تغییر ذخیره شد.',reply_markup=tournament_manage_menu(tid,t.group_id)); return
        if not t: await state.clear(); await message.answer('تورنمنت پیدا نشد.'); return
        if data.get('action')=='add_player':
            group=await session.get(Group,t.group_id)
            users=await _tour_users(session,[value],bot=message.bot,group=group)
            if not users: await message.answer('بازیکن پیدا نشد.'); return
            if not await session.scalar(select(TournamentPlayer.id).where(TournamentPlayer.tournament_id==tid,TournamentPlayer.user_id==users[0].id)): session.add(TournamentPlayer(tournament_id=tid,user_id=users[0].id))
            await session.commit(); await state.clear(); await message.answer('✅ بازیکن اضافه شد.',reply_markup=tournament_manage_menu(tid,t.group_id)); return
        if data.get('action')=='score':
            prizes=_tour_prizes(t.prize_points); entries=value.splitlines(); users=await _tour_users(session,[x.split(maxsplit=1)[1] for x in entries if len(x.split(maxsplit=1))==2])
            for line in entries:
                p=line.split(maxsplit=1)
                if len(p)!=2 or not p[0].isdigit(): continue
                matches=await _tour_users(session,[p[1]])
                if not matches: continue
                tp=await session.scalar(select(TournamentPlayer).where(TournamentPlayer.tournament_id==tid,TournamentPlayer.user_id==matches[0].id))
                if tp: tp.final_rank=int(p[0]); tp.awarded_points=prizes[int(p[0])-1] if 0<int(p[0])<=len(prizes) else 0
            await session.commit(); await state.clear(); await message.answer('✅ رتبه و امتیاز ثبت شد.',reply_markup=tournament_manage_menu(tid,t.group_id)); return
        if data.get('action')=='final':
            users=await _tour_users(session,value.splitlines())
            for u in users:
                if not await session.scalar(select(TournamentPlayer.id).where(TournamentPlayer.tournament_id==tid,TournamentPlayer.user_id==u.id)): session.add(TournamentPlayer(tournament_id=tid,user_id=u.id))
            await session.commit(); await state.clear(); await message.answer(f'✅ {len(users)} بازیکن برای فینال ثبت شد.',reply_markup=tournament_manage_menu(tid,t.group_id)); return
        if data.get('action')=='draw_count':
            try: count=int(value); assert count>0
            except: await message.answer('تعداد گروه باید عدد مثبت باشد.'); return
            await state.update_data(group_count=count); await message.answer('منبع قرعه‌کشی را انتخاب کن:',reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='👥 بازیکنان ثبت‌شده',callback_data=f'tournament:draw_registered:{tid}'),InlineKeyboardButton(text='✍️ ورود دستی اسامی',callback_data=f'tournament:draw_manual:{tid}')]])); return
        if data.get('action')=='draw_manual':
            # Accept both one-name-per-line and comma/semicolon separated input.
            entries=[x.strip() for x in re.split(r'[\\n,،;؛]+', value) if x.strip()]
            t=await session.get(Tournament,int(data.get('tid',0)))
            if not t:
                await state.clear()
                await message.answer('تورنمنت پیدا نشد.')
                return
            group=await session.get(Group,t.group_id)
            users,unresolved=await _tour_users(session,entries,bot=message.bot,group=group)
            count=int(data['group_count'])
            if len(users)<count:
                await message.answer(
                    f'❌ برای {count} گروه حداقل {count} بازیکن لازم است؛ '
                    f'از اسامی ارسالی فقط {len(users)} بازیکن قابل شناسایی بود.\\n'
                    f'❓ پیدا نشد: {", ".join(unresolved[:10]) if unresolved else "—"}\\n'
                    'اسم/یوزرنیم بازیکنان را هر کدام در یک خط، یا با ویرگول/؛ جدا کن.'
                )
                return
            import random; random.shuffle(users)
            old=list((await session.execute(select(TournamentGroup).where(TournamentGroup.tournament_id==tid))).scalars().all())
            for g in old: await session.delete(g)
            for n in range(1,count+1): session.add(TournamentGroup(tournament_id=tid,group_no=n,name=f'گروه {n}'))
            await session.flush()
            for i,u in enumerate(users):
                tp=await session.scalar(select(TournamentPlayer).where(TournamentPlayer.tournament_id==tid,TournamentPlayer.user_id==u.id))
                if tp: tp.group_no=i%count+1
                else: session.add(TournamentPlayer(tournament_id=tid,user_id=u.id,group_no=i%count+1))
            t.group_count=count; await session.commit(); await state.clear(); await message.answer('🎲 قرعه‌کشی انجام شد.',reply_markup=tournament_manage_menu(tid,t.group_id)); return
@router.callback_query(lambda c: c.data.startswith('tournament:open:'))
async def tournament_open(callback: CallbackQuery):
    tid=int(callback.data.rsplit(':',1)[1])
    async with session_factory() as session:
        t=await _tour_allowed(session,callback.bot,callback.from_user.id,tid)
    if not t: await callback.answer('دسترسی ندارید.',show_alert=True); return
    await callback.message.edit_text('🏆 مدیریت تورنمنت',reply_markup=tournament_manage_menu(tid,t.group_id)); await callback.answer()

@router.callback_query(lambda c: c.data.startswith('tournament:link_game:'))
async def tournament_link_game(callback: CallbackQuery):
    tid=int(callback.data.rsplit(':',1)[1])
    async with session_factory() as session:
        t=await _tour_allowed(session,callback.bot,callback.from_user.id,tid)
        if not t: await callback.answer('دسترسی ندارید.',show_alert=True); return
        games=list((await session.execute(select(Game).where(Game.group_id==t.group_id,Game.tournament_id.is_(None)).order_by(Game.id.desc()).limit(20))).scalars().all())
    b=InlineKeyboardBuilder()
    for g in games:
        b.row(InlineKeyboardButton(text=f'🎮 بازی #{g.id}',callback_data=f'tournament:link_game_pick:{tid}:{g.id}'))
    b.row(InlineKeyboardButton(text='↩️ بازگشت',callback_data=f'tournament:open:{tid}'))
    await callback.message.edit_text('🎮 بازی موردنظر را انتخاب کن تا به این تورنمنت متصل شود:',reply_markup=b.as_markup()); await callback.answer()

@router.callback_query(lambda c: c.data.startswith('tournament:link_game_pick:'))
async def tournament_link_game_pick(callback: CallbackQuery):
    _,_,_,tid,gid=callback.data.split(':'); tid=int(tid); gid=int(gid)
    async with session_factory() as session:
        t=await _tour_allowed(session,callback.bot,callback.from_user.id,tid)
        g=await session.get(Game,gid)
        if not t or not g or g.group_id!=t.group_id:
            await callback.answer('بازی معتبر نیست.',show_alert=True); return
        if g.tournament_id and g.tournament_id!=tid:
            await callback.answer('این بازی قبلاً به تورنمنت دیگری متصل شده.',show_alert=True); return
        g.tournament_id=tid; await session.commit()
    await callback.message.edit_text('✅ بازی به تورنمنت اضافه شد.',reply_markup=tournament_manage_menu(tid,t.group_id)); await callback.answer()

@router.callback_query(lambda c: c.data.startswith('tournament:delete:'))
async def tournament_delete(callback: CallbackQuery):
    tid=int(callback.data.rsplit(':',1)[1])
    async with session_factory() as session:
        t=await _tour_allowed(session,callback.bot,callback.from_user.id,tid)
        if not t: await callback.answer('دسترسی ندارید.',show_alert=True); return
        gid=t.group_id; await session.delete(t); await session.commit()
    await callback.message.edit_text('🗑 تورنمنت حذف شد.',reply_markup=tournament_admin_menu(gid)); await callback.answer()

@router.callback_query(lambda c: c.data.startswith('tournament:add_player:') or c.data.startswith('tournament:score:') or c.data.startswith('tournament:final:'))
async def tournament_input_start(callback: CallbackQuery,state:FSMContext):
    action,tid=callback.data.split(':')[1],int(callback.data.rsplit(':',1)[1])
    prompts={'add_player':'👤 نام بازیکن را دقیق بفرست.','score':'🏅 رتبه و نام بازیکن را هر کدام در یک خط بفرست؛ مثال: 1 علی\n2 رضا','final':'🏁 اسامی بازیکنان فینال را هر کدام در یک خط بفرست.'}
    async with session_factory() as session:
        t=await _tour_allowed(session,callback.bot,callback.from_user.id,tid)
    if not t: await callback.answer('دسترسی ندارید.',show_alert=True); return
    await state.clear(); await state.update_data(action=action,tid=tid); await state.set_state(TournamentState.input)
    await callback.message.edit_text(prompts[action]); await callback.answer()

@router.callback_query(lambda c: c.data.startswith('tournament:draw:'))
async def tournament_draw_start(callback: CallbackQuery,state:FSMContext):
    tid=int(callback.data.rsplit(':',1)[1])
    async with session_factory() as session: t=await _tour_allowed(session,callback.bot,callback.from_user.id,tid)
    if not t: await callback.answer('دسترسی ندارید.',show_alert=True); return
    await state.clear(); await state.update_data(action='draw_count',tid=tid); await state.set_state(TournamentState.input)
    await callback.message.edit_text('🎲 تعداد گروه‌ها را وارد کن.'); await callback.answer()

@router.callback_query(lambda c: c.data.startswith('tournament:draw_registered:'))
async def tournament_draw_registered(callback: CallbackQuery,state:FSMContext):
    tid=int(callback.data.rsplit(':',1)[1]); data=await state.get_data(); count=int(data.get('group_count',0))
    async with session_factory() as session:
        t=await _tour_allowed(session,callback.bot,callback.from_user.id,tid)
        users=list((await session.execute(select(User).join(TournamentPlayer,TournamentPlayer.user_id==User.id).where(TournamentPlayer.tournament_id==tid))).scalars().all())
        if not t or not count or len(users)<count: await callback.answer('تعداد بازیکنان برای این قرعه کافی نیست.',show_alert=True); return
        import random; random.shuffle(users)
        old=list((await session.execute(select(TournamentGroup).where(TournamentGroup.tournament_id==tid))).scalars().all())
        for g in old: await session.delete(g)
        for n in range(1,count+1): session.add(TournamentGroup(tournament_id=tid,group_no=n,name=f'گروه {n}'))
        await session.flush()
        for i,u in enumerate(users): (await session.scalar(select(TournamentPlayer).where(TournamentPlayer.tournament_id==tid,TournamentPlayer.user_id==u.id))).group_no=i%count+1
        t.group_count=count; await session.commit()
    await state.clear(); await callback.message.edit_text('🎲 قرعه‌کشی انجام شد.',reply_markup=tournament_manage_menu(tid,t.group_id)); await callback.answer()

@router.callback_query(lambda c: c.data.startswith('tournament:draw_manual:'))
async def tournament_draw_manual_start(callback: CallbackQuery,state:FSMContext):
    tid=int(callback.data.rsplit(':',1)[1]); data=await state.get_data()
    await state.update_data(action='draw_manual',tid=tid,group_count=int(data.get('group_count',0))); await state.set_state(TournamentState.input)
    await callback.message.edit_text('✍️ اسامی بازیکنان را هر کدام در یک خط بفرست.'); await callback.answer()

@router.callback_query(lambda c: c.data.startswith('tournament:finish:'))
async def tournament_finish(callback: CallbackQuery):
    tid=int(callback.data.rsplit(':',1)[1])
    async with session_factory() as session:
        t=await _tour_allowed(session,callback.bot,callback.from_user.id,tid)
        if not t: await callback.answer('دسترسی ندارید.',show_alert=True); return
        players=list((await session.execute(select(TournamentPlayer).where(TournamentPlayer.tournament_id==tid))).scalars().all())
        if t.status == 'finished': await callback.answer('این تورنمنت قبلاً تمام شده است.',show_alert=True); return
        if not any(p.final_rank for p in players): await callback.answer('ابتدا رتبه‌ها را ثبت کن.',show_alert=True); return
        for p in players:
            if p.final_rank and p.awarded_points: (await session.get(User,p.user_id)).score += p.awarded_points
        t.status='finished'; t.finished_at=datetime.now(timezone.utc); await session.commit(); gid=t.group_id
    await callback.message.edit_text('🏆 تورنمنت تمام شد و امتیازها به پروفایل بازیکنان اضافه شد.',reply_markup=tournament_admin_menu(gid)); await callback.answer()

@router.callback_query(lambda c: c.data.startswith('tournament:groups:'))
async def tournament_groups(callback: CallbackQuery):
    tid=int(callback.data.rsplit(':',1)[1])
    async with session_factory() as session:
        t=await session.get(Tournament,tid); groups=list((await session.execute(select(TournamentGroup).where(TournamentGroup.tournament_id==tid).order_by(TournamentGroup.group_no))).scalars().all())
    b=InlineKeyboardBuilder()
    for g in groups: b.row(InlineKeyboardButton(text=f'👥 {g.name}',callback_data=f'tournament:groupmenu:{tid}:{g.id}'))
    b.row(InlineKeyboardButton(text='↩️ بازگشت',callback_data=f'tournament:open:{tid}'))
    await callback.message.edit_text('👥 مدیریت گروه‌ها',reply_markup=b.as_markup()); await callback.answer()

@router.callback_query(lambda c: c.data.startswith('tournament:groupmenu:'))
async def tournament_groupmenu(callback: CallbackQuery):
    _,_,tid,gid=callback.data.split(':'); tid=int(tid); gid=int(gid)
    b=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='✏️ تغییر نام گروه',callback_data=f'tournament:group_rename:{tid}:{gid}')],[InlineKeyboardButton(text='➕ اضافه کردن بازیکن',callback_data=f'tournament:group_add:{tid}:{gid}')],[InlineKeyboardButton(text='➖ حذف بازیکن',callback_data=f'tournament:group_remove:{tid}:{gid}')],[InlineKeyboardButton(text='🗑 حذف گروه',callback_data=f'tournament:group_delete:{tid}:{gid}')],[InlineKeyboardButton(text='↩️ بازگشت',callback_data=f'tournament:groups:{tid}')]])
    await callback.message.edit_text('👥 مدیریت گروه',reply_markup=b); await callback.answer()

@router.callback_query(lambda c: c.data.startswith('tournament:group_rename:') or c.data.startswith('tournament:group_add:') or c.data.startswith('tournament:group_remove:'))
async def tournament_group_input(callback: CallbackQuery,state:FSMContext):
    action,tid,gid=callback.data.split(':')[1:]; tid=int(tid); gid=int(gid)
    mapped={'group_rename':'rename_group','group_add':'group_add','group_remove':'group_remove'}
    await state.clear(); await state.update_data(action=mapped[action],tid=tid,group_id_no=gid); await state.set_state(TournamentState.input)
    await callback.message.edit_text({'group_rename':'✏️ نام جدید گروه را بفرست.','group_add':'➕ نام بازیکن را بفرست.','group_remove':'➖ نام بازیکن را بفرست.'}[action]); await callback.answer()

@router.callback_query(lambda c: c.data.startswith('tournament:group_delete:'))
async def tournament_group_delete(callback: CallbackQuery):
    _,_,tid,gid=callback.data.split(':'); tid=int(tid); gid=int(gid)
    async with session_factory() as session:
        t=await session.get(Tournament,tid); g=await session.get(TournamentGroup,gid)
        if t and g:
            for p in (await session.execute(select(TournamentPlayer).where(TournamentPlayer.tournament_id==tid,TournamentPlayer.group_no==g.group_no))).scalars(): p.group_no=None
            await session.delete(g); await session.commit()
    await callback.message.edit_text('🗑 گروه حذف شد.',reply_markup=tournament_manage_menu(tid,t.group_id if t else 0)); await callback.answer()

async def _tour_member(session,t,user_id):
    u=await session.scalar(select(User).where(User.telegram_id==user_id))
    if not u: return False
    return bool(await session.scalar(select(TournamentPlayer.id).where(TournamentPlayer.tournament_id==t.id,TournamentPlayer.user_id==u.id))) or bool(await session.scalar(select(GamePlayer.id).join(Game,Game.id==GamePlayer.game_id).where(GamePlayer.user_id==u.id,Game.group_id==t.group_id)))

@router.callback_query(lambda c: c.data=='menu:tournaments')
async def public_tournaments(callback: CallbackQuery):
    async with session_factory() as session:
        u=await session.scalar(select(User).where(User.telegram_id==callback.from_user.id))
        ts=list((await session.execute(select(Tournament).join(Game,Game.group_id==Tournament.group_id).join(GamePlayer,GamePlayer.game_id==Game.id).where(GamePlayer.user_id==u.id,Tournament.status=='active').distinct().order_by(Tournament.start_at.desc()))).scalars().all()) if u else []
    b=InlineKeyboardBuilder()
    for t in ts: b.row(InlineKeyboardButton(text=f'{t.emoji} {t.name[:50]}',callback_data=f'tourpub:open:{t.id}'))
    b.row(InlineKeyboardButton(text='↩️ بازگشت',callback_data='menu:root'))
    await callback.message.edit_text('🏆 تورنمنت‌های فعال:',reply_markup=b.as_markup())
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith('tourpub:open:'))
async def public_tournament_open(callback: CallbackQuery):
    tid=int(callback.data.rsplit(':',1)[1])
    async with session_factory() as session:
        t=await session.get(Tournament,tid)
        if not t or not await _tour_member(session,t,callback.from_user.id): await callback.answer('این تورنمنت برای شما قابل مشاهده نیست.',show_alert=True); return
    await callback.message.edit_text('🏆 تورنمنت',reply_markup=tournament_public_menu(tid)); await callback.answer()

@router.callback_query(lambda c: c.data.startswith('tourpub:scores:') or c.data.startswith('tourpub:groups:') or c.data.startswith('tourpub:games:'))
async def public_tournament_section(callback: CallbackQuery):
    section,raw=callback.data.split(':')[1:]; tid=int(raw)
    async with session_factory() as session:
        t=await session.get(Tournament,tid)
        if not t or not await _tour_member(session,t,callback.from_user.id): await callback.answer('دسترسی ندارید.',show_alert=True); return
        rows=list((await session.execute(select(TournamentPlayer,User).join(User,User.id==TournamentPlayer.user_id).where(TournamentPlayer.tournament_id==tid).order_by(TournamentPlayer.final_rank.is_(None),TournamentPlayer.final_rank,TournamentPlayer.awarded_points.desc()))).all())
        if section=='scores':
            body=''.join(f'<tr><td align="center">{p.final_rank or "—"}</td><td>{escape(u.display_name or u.first_name or "بازیکن")}</td><td align="center"><b>{p.awarded_points}</b></td></tr>' for p,u in rows)
            html=f'<h2>{t.emoji} {escape(t.name)}</h2><table bordered striped compact><tr><th>رتبه</th><th>بازیکن</th><th>امتیاز</th></tr>{body}</table>'
        elif section=='groups':
            groups=list((await session.execute(select(TournamentGroup).where(TournamentGroup.tournament_id==tid).order_by(TournamentGroup.group_no))).scalars().all())
            parts=[]
            for g in groups:
                names=' • '.join(escape(u.display_name or u.first_name or 'بازیکن') for p,u in rows if p.group_no==g.group_no)
                parts.append(f'<h3>👥 {escape(g.name)}</h3><p>{names or "خالی"}</p>')
            html=f'<h2>{t.emoji} {escape(t.name)}</h2>'+''.join(parts)
        else:
            games=list((await session.execute(select(Game,Scenario).join(Scenario,Scenario.id==Game.scenario_id).where(Game.tournament_id==tid).order_by(Game.id))).all())
            body=''.join(f'<tr><td>#{g.id}</td><td>{escape(s.name_fa)}</td><td>{_status_fa(g.status)}</td></tr>' for g,s in games)
            html=f'<h2>{t.emoji} {escape(t.name)}</h2><table bordered striped compact><tr><th>بازی</th><th>سناریو</th><th>وضعیت</th></tr>{body}</table>' if body else f'<h2>{t.emoji} {escape(t.name)}</h2><p>هنوز بازی‌ای ثبت نشده است.</p>'
    try: await edit_rich_message(callback.bot,callback.message.chat.id,callback.message.message_id,html)
    except Exception: await callback.message.edit_text(re.sub('<[^>]+>','',html),reply_markup=tournament_public_menu(tid))
    await callback.answer()
@router.callback_query(lambda c: c.data.startswith('tournament:edit:'))
async def tournament_edit_start(callback: CallbackQuery,state:FSMContext):
    tid=int(callback.data.rsplit(':',1)[1])
    async with session_factory() as session: t=await _tour_allowed(session,callback.bot,callback.from_user.id,tid)
    if not t: await callback.answer('دسترسی ندارید.',show_alert=True); return
    await state.clear(); await state.update_data(action='edit',tid=tid,step='name'); await state.set_state(TournamentState.input)
    await callback.message.edit_text(f'✏️ نام جدید تورنمنت را بفرست.\nفعلی: {t.name}\nبرای حفظ نام: -'); await callback.answer()

@router.message(BirthdayAdminState.video)
async def admin_birthday_video_save(message: Message, state: FSMContext) -> None:
    if message.chat.type != "private" or not message.from_user or message.from_user.id not in get_settings().admin_id_set:
        return
    if (message.text or "").strip() == "/cancel":
        await state.clear()
        await message.answer("❌ تغییر ویدیوی تبریک لغو شد.", reply_markup=admin_panel_menu())
        return
    if not message.video:
        await message.answer("❌ لطفاً خودِ ویدیو را ارسال کن، نه فایل یا متن. برای لغو /cancel را بفرست.")
        return
    async with session_factory() as session:
        setting = await session.scalar(select(BirthdaySetting).where(BirthdaySetting.id == 1))
        if not setting:
            setting = BirthdaySetting(id=1)
            session.add(setting)
        setting.video_file_id = message.video.file_id
        setting.enabled = True
        await session.commit()
        messages = list((await session.execute(
            select(BirthdayMessageTemplate).order_by(BirthdayMessageTemplate.id)
        )).scalars().all())
    await state.clear()
    await message.answer(
        "✅ ویدیوی تبریک تولد ذخیره شد.\nاز این به بعد ویدیوی جدید در تبریک‌های روزانه استفاده می‌شود.",
        reply_markup=birthday_admin_menu(message.video.file_id, len(messages)),
    )


@router.message(BirthdayAdminState.message)
async def admin_birthday_message_save(message: Message, state: FSMContext) -> None:
    if message.chat.type != "private" or not message.from_user or message.from_user.id not in get_settings().admin_id_set:
        return
    raw = (message.text or "").strip()
    if raw == "/cancel":
        await state.clear()
        await message.answer("❌ افزودن پیام تبریک لغو شد.", reply_markup=admin_panel_menu())
        return
    if not raw:
        await message.answer("❌ متن پیام خالی است. متن تبریک را ارسال کن.")
        return
    allowed = {"name", "first_name", "username", "mention", "user_id", "birthday", "age"}
    import re
    unknown = sorted(set(re.findall(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", raw)) - allowed)
    if unknown:
        await message.answer(
            "❌ این متغیرها شناخته‌شده نیستند: "
            + ", ".join("{" + item + "}" for item in unknown)
            + "\nاز متغیرهای راهنما استفاده کن."
        )
        return
    async with session_factory() as session:
        item = BirthdayMessageTemplate(text=raw, enabled=True)
        session.add(item)
        await session.commit()
        messages = list((await session.execute(
            select(BirthdayMessageTemplate).order_by(BirthdayMessageTemplate.id)
        )).scalars().all())
        setting = await session.scalar(select(BirthdaySetting).where(BirthdaySetting.id == 1))
    await state.clear()
    await message.answer(
        "✅ پیام تبریک جدید اضافه شد.",
        reply_markup=birthday_admin_menu(setting.video_file_id if setting else None, len(messages)),
    )
