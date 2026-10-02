from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from html import escape
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from sqlalchemy import desc, func, select
import json

from app.db.models import Game, GameEvent, GamePlayer, Group, GroupSettings, Role, Scenario, ScenarioRole, User, Vote
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
    main_menu,
    player_management_menu,
    player_target_management_keyboard,
    ranking_menu,
    admin_panel_menu,
    admin_scenario_keyboard,
    scenario_management_menu,
    scenario_admin_list_keyboard,
    scenario_role_keyboard,
    scenario_challenge_keyboard,
    scenario_delete_confirm_keyboard,
    notification_settings_menu,
    finish_game_confirm_keyboard,
    game_result_keyboard,
    game_result_back_keyboard,
    scenario_select_keyboard,
    host_select_keyboard,
    game_event_management_keyboard,
)
from app.repositories.games import GameRepository
from app.repositories.users import UserRepository
from app.services.game import create_game
from app.services.profile import sync_telegram_user
from app.services.gameplay import current_round, _event
from app.services.stats import leaderboard, rank_for_score
from app.config import get_settings
from app.utils.text import tg_name, tg_mention
from uuid import uuid4

router = Router(name="menu")

class GameEventState(StatesGroup):
    description = State()


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
        select(Group).where(Group.is_active.is_(True), Group.registered_at.is_not(None)).order_by(Group.title)
    )
    groups = []
    for group in result.scalars().all():
        if await _is_group_admin(bot, group, user_id) and await _bot_is_active(bot, group):
            groups.append(group)
    return groups


async def _selected_group(session, bot, user_id: int, group_id: int) -> Group | None:
    group = await session.get(Group, group_id)
    if not group or not group.is_active or group.registered_at is None:
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

    leader_id = None
    leader_event = await session.scalar(select(GameEvent).where(
        GameEvent.game_id == game.id, GameEvent.event_type == "leader_selected"
    ).order_by(GameEvent.id.desc()))
    if leader_event:
        try:
            leader_id = int(json.loads(leader_event.payload or "{}").get("leader_user_id"))
        except (TypeError, ValueError):
            pass

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
        f"📓 <b>بازی شماره : {game.id}</b>",
        f"⏱️ زمان : {when:%H:%M}",
        f"📆 تاریخ : {_jalali_date(when)}",
        f"🗓 سناریو : {escape(scenario.name_fa if scenario else 'نامشخص')}",
        f"👮‍♂️ گرداننده : {tg_mention(host.telegram_id, host.display_name or host.first_name or 'گرداننده') if host else 'نامشخص'}",
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
        if team == "mafia":
            badges.append("🩸")
        elif team == "citizen":
            badges.append("🏆" if winner == "citizen" else "🔵")
        elif team == "independent":
            badges.append("🧭" if winner in {"independent", "citizen_independent"} else "🟣")
        if player.alive and ((winner == "mafia" and team == "mafia") or
                             (winner == "citizen" and team == "citizen") or
                             (winner == "independent" and team == "independent") or
                             (winner == "citizen_independent" and team in {"citizen", "independent"})):
            if "🏆" not in badges:
                badges.append("🏆")
        if not player.alive:
            badges.append("☠️")
            if player.exit_type == "kick" and emoji_settings.get("kick", True):
                badges.append("⛔")
            elif player.exit_type == "slaughter" and emoji_settings.get("slaughter", True):
                badges.append("🩸")
            elif player.exit_type == "vote":
                badges.append("🗳")
            elif player.exit_type == "faceoff":
                badges.append("🎭")
        if user.id == leader_id:
            badges.append("👑")
        if player.warning_count and emoji_settings.get("warning", True):
            badges.append(f"⚠️{player.warning_count}")
        if player.silence_until_round is not None and emoji_settings.get("silence", True):
            badges.append("🔇")
        if player.extra_turn_round is not None and emoji_settings.get("extra_turn", True):
            badges.append("➕")
        if user.id in challenge_ids and emoji_settings.get("challenge", True):
            badges.append("🤏🏻")
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
async def admin_panel_handler(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    if callback.message.chat.type != "private" or callback.from_user.id not in get_settings().admin_id_set:
        await callback.answer("دسترسی پنل مدیریت مجاز نیست.", show_alert=True)
        return
    action = callback.data.split(":", 1)[1]
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
                lines.append(f"#{game.id} — {scenario.name_fa} — {game.status} / {game.phase}")
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


@router.callback_query(lambda c: c.data == "menu:root")
async def menu_root(callback: CallbackQuery) -> None:
    if not callback.message:
        return
    await callback.message.edit_text("منوی اصلی", reply_markup=main_menu())
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
                reply_markup=group_list_keyboard(groups, "games"),
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


@router.callback_query(lambda c: c.data.startswith("groupmgmt:select:"))
async def select_group(callback: CallbackQuery) -> None:
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
            settings = (await session.execute(
                select(GroupSettings).where(GroupSettings.group_id == group.id)
            )).scalar_one_or_none()
            if settings is None:
                settings = GroupSettings(group_id=group.id)
                session.add(settings)
                await session.commit()
            await callback.message.edit_text(
                f"قفل‌های گروه «{group.title or group.telegram_id}»",
                reply_markup=group_lock_keyboard(group.id, settings),
            )
        else:
            await callback.message.edit_text(
                f"گروه: {group.title or group.telegram_id}\n\nبخش موردنظر را انتخاب کنید.",
                reply_markup=group_game_menu(group.id),
            )
    await callback.answer()


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
                f"وضعیت: {game.status}\nمرحله: {game.phase}",
                reply_markup=active_game_menu(group.id, f"gameadmin:lobby:{game.game_key}" if callback.message.chat.type in ("group", "supergroup") else f"gameadmin:active:{group.id}"),
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
                    f"#{game.id} — {scenario.name_fa} — {game.status} — {game.phase}"
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
            reply_markup=active_game_menu(group.id),
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
                f"وضعیت: {game.status}\nمرحله: {game.phase}\n"
                f"گرداننده: {host.display_name if host else 'نامشخص'}\n\n"
                f"بازیکنان:\n{player_lines}",
                reply_markup=active_game_menu(group.id, f"gameadmin:lobby:{game.game_key}" if callback.message.chat.type in ("group", "supergroup") else f"gameadmin:active:{group.id}"),
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
            if player.is_reserved:
                lines.append(f"رزرو {player.reserve_position}. {tg_name(user.display_name or user.first_name)} — رزرو")
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

@router.callback_query(lambda c: c.data.startswith("gameadmin:scenario:"))
async def gameadmin_scenario_select(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    key = callback.data.split(":", 2)[2]
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
                back_callback=f"game:return_lobby:{game.game_key}",
                callback_prefix=f"gameadmin:setscenario:{game.game_key}",
            ),
        )
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("gameadmin:setscenario:"))
async def gameadmin_set_scenario(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    parts = callback.data.split(":")
    if len(parts) != 5:
        await callback.answer("درخواست تغییر سناریو نامعتبر است.", show_alert=True)
        return
    key, scenario_raw = parts[2], parts[4]
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
        # Render the actual lobby in the same group-management message.
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


@router.callback_query(lambda c: c.data.startswith("gameadmin:host:"))
async def gameadmin_host_select(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    key = callback.data.split(":", 2)[2]
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
                callback_prefix=f"gameadmin:sethost:{game.game_key}",
                back_callback=f"game:return_lobby:{game.game_key}",
            ),
        )
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("gameadmin:sethost:"))
async def gameadmin_set_host(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    parts = callback.data.split(":")
    if len(parts) != 5:
        await callback.answer("درخواست تغییر گرداننده نامعتبر است.", show_alert=True)
        return
    key, host_raw = parts[2], parts[4]
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
        try:
            from app.handlers.gameplay import delete_main_roster
            await delete_main_roster(callback.bot, session, game)
            await callback.bot.send_message(
                group.telegram_id,
                "❌ بازی توسط گرداننده لغو شد."
            )
        except Exception:
            pass
        await callback.message.edit_text("بازی لغو شد و سوابق آن برای تاریخچه حفظ شد.", reply_markup=group_game_menu(group.id))
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
            reply_markup=finish_game_confirm_keyboard(group.id, winner),
            parse_mode="HTML",
        )
    await callback.answer("نتیجه انتخاب شد؛ تأیید کنید.")


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
            from app.handlers.gameplay import delete_main_roster
            await delete_main_roster(callback.bot, session, game)
        except ValueError as exc:
            await callback.answer(str(exc), show_alert=True)
            return
        await callback.message.edit_text(
            await _game_result_text(session, game, winner),
            reply_markup=game_result_keyboard(group.id, game.id),
            parse_mode="HTML",
        )
    await callback.answer("نتیجه بازی ثبت شد.")




@router.callback_query(lambda c: c.data.startswith("gameadmin:events:"))
async def game_event_management(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    group_id = int(callback.data.rsplit(":", 1)[1])
    async with session_factory() as session:
        group = await _selected_group(session, callback.bot, callback.from_user.id, group_id)
        game = await GameRepository.get_active(session, group.id) if group else None
        if not game:
            await callback.answer("بازی فعالی وجود ندارد.", show_alert=True)
            return
        if game.auto_play:
            await callback.answer("ثبت دستی اتفاقات فقط برای بازی غیرخودکار فعال است.", show_alert=True)
            return
        result = await session.execute(
            select(GameEvent).where(
                GameEvent.game_id == game.id,
                GameEvent.event_type == "manual_game_event",
            ).order_by(GameEvent.id.desc()).limit(10)
        )
        events = list(result.scalars())
        lines = ["📜 <b>اتفاقات ثبت‌شده بازی</b>", ""]
        if not events:
            lines.append("هنوز اتفاق دستی ثبت نشده است.")
        else:
            for event in reversed(events):
                data = json.loads(event.payload or "{}")
                lines.append(f"• دور {data.get('round_no', '-')} — {escape(str(data.get('text', '')))}")
        await callback.message.edit_text("\n".join(lines), reply_markup=game_event_management_keyboard(group.id), parse_mode="HTML")
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("gameadmin:event_add:"))
async def game_event_add(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.message or not callback.from_user:
        return
    group_id = int(callback.data.rsplit(":", 1)[1])
    async with session_factory() as session:
        group = await _selected_group(session, callback.bot, callback.from_user.id, group_id)
        game = await GameRepository.get_active(session, group.id) if group else None
        if not game or game.auto_play:
            await callback.answer("ثبت اتفاق دستی برای این بازی فعال نیست.", show_alert=True)
            return
    await state.set_state(GameEventState.description)
    await state.update_data(group_id=group_id)
    await callback.message.answer("متن اتفاق بازی را ارسال کنید:")
    await callback.answer()


@router.message(GameEventState.description)
async def game_event_add_text(message: Message, state: FSMContext) -> None:
    if not message.from_user or not message.text:
        return
    data = await state.get_data()
    group_id = data.get("group_id")
    async with session_factory() as session:
        group = await _selected_group(session, message.bot, message.from_user.id, int(group_id)) if group_id else None
        game = await GameRepository.get_active(session, group.id) if group else None
        if not game or game.auto_play:
            await state.clear()
            await message.answer("بازی فعال یا دسترسی لازم وجود ندارد.")
            return
        actor = await UserRepository(session).get_by_telegram_id(message.from_user.id)
        await _event(
            session,
            game,
            "manual_game_event",
            {"round_no": await current_round(session, game.id), "text": message.text.strip()},
            actor.id if actor else None,
        )
        await session.commit()
    await state.clear()
    await message.answer("اتفاق بازی ثبت شد.")


@router.callback_query(lambda c: c.data.startswith("gameresult:back:"))
async def game_result_back(callback: CallbackQuery) -> None:
    game_id = int(callback.data.rsplit(":", 1)[1])
    async with session_factory() as session:
        game = await session.get(Game, game_id)
        if not game:
            await callback.answer("بازی پیدا نشد.", show_alert=True)
            return
        winner_event = await session.scalar(select(GameEvent).where(
            GameEvent.game_id == game.id, GameEvent.event_type.in_(["game_finished", "stats_recorded"])
        ).order_by(GameEvent.id.desc()))
        winner = (json.loads(winner_event.payload or "{}").get("winner") if winner_event else "draw")
        await callback.message.edit_text(
            await _game_result_text(session, game, winner),
            reply_markup=game_result_keyboard((await session.get(Group, game.group_id)).id, game.id),
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("gameresult:register:"))
async def game_result_register(callback: CallbackQuery) -> None:
    game_id = int(callback.data.rsplit(":", 1)[1])
    async with session_factory() as session:
        game = await session.get(Game, game_id)
        if not game:
            await callback.answer("بازی پیدا نشد.", show_alert=True)
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
        rounds = await session.scalar(select(func.count(GameEvent.id)).where(GameEvent.game_id == game.id, GameEvent.event_type == "round_started"))
        challenges = await session.scalar(select(func.count(GameEvent.id)).where(GameEvent.game_id == game.id, GameEvent.event_type == "challenge_request"))
        nights = await session.scalar(select(func.count(GameEvent.id)).where(GameEvent.game_id == game.id, GameEvent.event_type == "night_resolved"))
        votes = await session.scalar(select(func.count(GameEvent.id)).where(GameEvent.game_id == game.id, GameEvent.event_type == "voting_resolved"))
        await callback.message.edit_text(f"📊 <b>آمار بازی</b>\n\nدورها: {rounds or 0}\nدرخواست‌های چالش: {challenges or 0}\nشب‌های حل‌شده: {nights or 0}\nرأی‌گیری‌های حل‌شده: {votes or 0}", reply_markup=game_result_back_keyboard(game.id))
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
        result = await session.execute(select(GameEvent).where(GameEvent.game_id == game.id).order_by(GameEvent.id.desc()).limit(25))
        events = list(result.scalars())
        lines = ["📜 <b>اتفاقات بازی</b>", ""]
        for event in reversed(events):
            data = json.loads(event.payload or "{}")
            round_no = data.get("round_no", "-")
            lines.append(f"دور {round_no} — {event.event_type}")
        await callback.message.edit_text("\n".join(lines), reply_markup=game_result_back_keyboard(game.id))
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
            if game.auto_play:
                await callback.answer("ثبت دستی اتفاقات فقط برای بازی غیرخودکار فعال است.", show_alert=True)
                return
            await callback.message.edit_text(
                "📜 <b>مدیریت اتفاقات بازی</b>\n\nاتفاقات این بازی را از پنل خصوصی ثبت کنید.",
                reply_markup=game_event_management_keyboard(group.id),
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
        if action == "auto_play":
            game.auto_play = not game.auto_play
        elif action == "turn_color_enabled":
            game.turn_color_enabled = not game.turn_color_enabled
        elif action == "turn_color":
            game.turn_color = colors[(colors.index(game.turn_color) + 1) % len(colors)] if game.turn_color in colors else colors[0]
        elif action == "challenge_color":
            game.challenge_color = colors[(colors.index(game.challenge_color) + 1) % len(colors)] if game.challenge_color in colors else colors[0]
        else:
            await callback.answer("امکان اضافی نامعتبر است.", show_alert=True)
            return
        await session.commit()
        await callback.message.edit_text(
            "امکانات اضافی بازی",
            reply_markup=game_extras_menu(group.id, game.auto_play, game.turn_color, game.challenge_color, game.turn_color_enabled),
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
    if not callback.message:
        return
    await callback.message.edit_text("🎭 مدیریت سناریوها\n\nایجاد، ویرایش یا حذف سناریوهای ذخیره‌شده در دیتابیس.", reply_markup=scenario_management_menu())
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
        text = "⚙️ تنظیمات عمومی\n\nتنظیمات رفتاری و شخصی ربات؛ مانند نمایش پروفایل و گزارش عملکرد."
        await callback.message.edit_text(text, reply_markup=bot_settings_menu())
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
        lines.append(f"#{game.id} — {scenario.name_fa} — {game.status} — {game.phase}")
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

    scenario = (await session.execute(
        select(Scenario).where(Scenario.enabled.is_(True), Scenario.key != "classic").order_by(Scenario.id)
    )).scalars().first()
    if not scenario:
        return None
    return await create_game(session, group, scenario, user, status="draft", reserve_enabled=True)


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

async def _scenario_admin_allowed(callback: CallbackQuery) -> bool:
    return bool(callback.from_user and callback.message and callback.message.chat.type == "private" and callback.from_user.id in get_settings().admin_id_set)

async def _scenario_form_roles(session, scenario_id: int) -> dict[int, int]:
    rows = (await session.execute(
        select(ScenarioRole).where(ScenarioRole.scenario_id == scenario_id).order_by(ScenarioRole.position, ScenarioRole.id)
    )).scalars().all()
    return {row.role_id: row.count for row in rows}

@router.callback_query(lambda c: c.data == "scenario_admin:create")
async def scenario_create_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _scenario_admin_allowed(callback):
        await callback.answer("دسترسی فقط برای مدیر ربات است.", show_alert=True)
        return
    await state.clear()
    await state.set_state(ScenarioAdminState.name)
    await state.update_data(mode="create")
    await callback.message.edit_text("➕ ایجاد سناریو\n\nنام سناریو را ارسال کنید:")
    await callback.answer()

@router.callback_query(lambda c: c.data == "scenario_admin:edit")
async def scenario_edit_list(callback: CallbackQuery) -> None:
    if not await _scenario_admin_allowed(callback):
        await callback.answer("دسترسی فقط برای مدیر ربات است.", show_alert=True)
        return
    async with session_factory() as session:
        scenarios = list((await session.execute(select(Scenario).where(Scenario.key != "classic").order_by(Scenario.id))).scalars().all())
    await callback.message.edit_text("✏️ سناریوی موردنظر را انتخاب کنید:", reply_markup=scenario_admin_list_keyboard(scenarios, "edit"))
    await callback.answer()

@router.callback_query(lambda c: c.data == "scenario_admin:delete")
async def scenario_delete_list(callback: CallbackQuery) -> None:
    if not await _scenario_admin_allowed(callback):
        await callback.answer("دسترسی فقط برای مدیر ربات است.", show_alert=True)
        return
    async with session_factory() as session:
        scenarios = list((await session.execute(select(Scenario).where(Scenario.key != "classic").order_by(Scenario.id))).scalars().all())
    await callback.message.edit_text("🗑 سناریوی موردنظر را برای حذف انتخاب کنید:", reply_markup=scenario_admin_list_keyboard(scenarios, "delete"))
    await callback.answer()

@router.callback_query(lambda c: c.data == "scenario_admin:cancel")
async def scenario_admin_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text("🎭 مدیریت سناریوها", reply_markup=scenario_management_menu())
    await callback.answer()


@router.message(ScenarioAdminState.name)
async def scenario_form_name(message: Message, state: FSMContext) -> None:
    if message.chat.type != "private" or not message.from_user or message.from_user.id not in get_settings().admin_id_set:
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
    await state.set_state(ScenarioAdminState.turn_time)
    await message.answer("زمان هر نوبت را وارد کنید (مثلاً 02:00 یا 120). پیش‌فرض: 02:00")

@router.message(ScenarioAdminState.min_players)
async def scenario_form_min(message: Message, state: FSMContext) -> None:
    # Kept as a compatibility state; new forms derive player count from roles.
    await state.set_state(ScenarioAdminState.turn_time)
    await message.answer("زمان هر نوبت را وارد کنید (مثلاً 02:00 یا 120 ثانیه). پیش‌فرض: 02:00")

@router.message(ScenarioAdminState.turn_time)
async def scenario_form_turn_time(message: Message, state: FSMContext) -> None:
    value = (message.text or "").strip()
    data = await state.get_data()
    if value == "-" and data.get("edit_id"):
        value = str(data.get("current_turn_seconds", 120))
    seconds = _parse_duration(value)
    if seconds is None or not 15 <= seconds <= 600:
        await message.answer("زمان نوبت باید بین ۱۵ ثانیه تا ۱۰ دقیقه باشد. مثال: 02:00")
        return
    await state.update_data(turn_seconds=seconds)
    await state.set_state(ScenarioAdminState.challenge_time)
    await message.answer("زمان چالش را وارد کنید. پیش‌فرض: 01:00")

@router.message(ScenarioAdminState.challenge_time)
async def scenario_form_challenge_time(message: Message, state: FSMContext) -> None:
    value = (message.text or "").strip()
    data = await state.get_data()
    if value == "-" and data.get("edit_id"):
        value = str(data.get("current_challenge_seconds", 60))
    seconds = _parse_duration(value)
    if seconds is None or not 15 <= seconds <= 600:
        await message.answer("زمان چالش باید بین ۱۵ ثانیه تا ۱۰ دقیقه باشد. مثال: 01:00")
        return
    await state.update_data(challenge_seconds=seconds)
    await state.set_state(ScenarioAdminState.extra_challenge_time)
    await message.answer("زمان چالش اضافه را وارد کنید. پیش‌فرض: 01:00")

@router.message(ScenarioAdminState.extra_challenge_time)
async def scenario_form_extra_challenge_time(message: Message, state: FSMContext) -> None:
    value = (message.text or "").strip()
    data = await state.get_data()
    if value == "-" and data.get("edit_id"):
        value = str(data.get("current_extra_challenge_seconds", 60))
    seconds = _parse_duration(value)
    if seconds is None or not 15 <= seconds <= 600:
        await message.answer("زمان چالش اضافه باید بین ۱۵ ثانیه تا ۱۰ دقیقه باشد. مثال: 01:00")
        return
    await state.update_data(extra_challenge_seconds=seconds)
    await state.set_state(ScenarioAdminState.challenge)
    await message.answer("تنظیم چالش را انتخاب کنید:", reply_markup=scenario_challenge_keyboard(data.get("mode", "create"), bool(data.get("edit_id"))))

@router.message(ScenarioAdminState.max_players)
async def scenario_form_max(message: Message, state: FSMContext) -> None:
    await scenario_form_min(message, state)

@router.callback_query(lambda c: c.data.startswith("scenario_admin:") and ":challenge:" in c.data)
async def scenario_form_challenge(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _scenario_admin_allowed(callback):
        await callback.answer("دسترسی غیرمجاز.", show_alert=True)
        return
    parts = callback.data.split(":")
    mode = parts[1]
    value = parts[3]
    data = await state.get_data()
    if value == "unchanged":
        value = data.get("challenge_mode", "limited")
    await state.update_data(challenge_mode=value, challenge_limit=(1 if value == "limited" else None))
    await state.set_state(ScenarioAdminState.vote_threshold)
    await callback.message.edit_text("قانون حدنصاب رای اول را وارد کنید:\n50 = حداقل ۵۰٪\n50+1 = در تعداد فرد، ۵۰٪ + ۱\n50-1 = در تعداد فرد، ۵۰٪ − ۱\nعدد = حدنصاب ثابت\nپیش‌فرض: 50")
    await callback.answer()
    return

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
    await state.set_state(ScenarioAdminState.roles)
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
        role_map = {(r.name_fa.strip(), r.team): r for r in role_rows}
        resolved = []
        for role_name, team in role_lines:
            role = role_map.get((role_name, team))
            if not role:
                await message.answer(f"نقش «{role_name}» با ساید «{team}» در فهرست نقش‌ها پیدا نشد.")
                return
            resolved.append(role)

        edit_id = data.get("edit_id")
        if edit_id:
            scenario = await session.get(Scenario, int(edit_id))
            if not scenario:
                await state.clear()
                await message.answer("سناریو پیدا نشد.", reply_markup=scenario_management_menu())
                return
            scenario.name_fa = data["name"]
            scenario.description = data.get("description", "")
            scenario.min_players = len(resolved)
            scenario.max_players = len(resolved)
            scenario.turn_seconds = int(data.get("turn_seconds", 120))
            scenario.challenge_seconds = int(data.get("challenge_seconds", 60))
            scenario.extra_challenge_seconds = int(data.get("extra_challenge_seconds", 60))
            scenario.challenge_mode = data.get("challenge_mode", "limited")
            scenario.challenge_limit = 1 if scenario.challenge_mode == "limited" else None
            scenario.vote_defense_threshold = int(data.get("vote_defense_threshold", 2))
            scenario.voting_rules = json.dumps(data.get("voting_rules", {}), ensure_ascii=False)
            old = list((await session.execute(select(ScenarioRole).where(ScenarioRole.scenario_id == scenario.id))).scalars().all())
            for row in old:
                await session.delete(row)
        else:
            scenario = Scenario(
                key="custom_" + uuid4().hex[:12],
                name_fa=data["name"],
                description=data.get("description", ""),
                min_players=len(resolved),
                max_players=len(resolved),
                enabled=True,
                turn_seconds=int(data.get("turn_seconds", 120)),
                challenge_seconds=int(data.get("challenge_seconds", 60)),
                extra_challenge_seconds=int(data.get("extra_challenge_seconds", 60)),
                vote_defense_threshold=int(data.get("vote_defense_threshold", 2)),
                voting_rules=json.dumps(data.get("voting_rules", {}), ensure_ascii=False),
                challenge_mode=data.get("challenge_mode", "limited"),
                challenge_limit=1 if data.get("challenge_mode") == "limited" else None,
            )
            session.add(scenario)
            await session.flush()

        for pos, role in enumerate(resolved):
            session.add(ScenarioRole(scenario_id=scenario.id, role_id=role.id, count=1, position=pos))
        await session.commit()

    await state.clear()
    await message.answer(
        f"✅ سناریو ذخیره شد.\nتعداد بازیکنان: {len(resolved)}\n"
        f"زمان نوبت: {_format_duration(int(data.get('turn_seconds', 120)))}\n"
        f"زمان چالش: {_format_duration(int(data.get('challenge_seconds', 60)))}\n"
        f"زمان چالش اضافه: {_format_duration(int(data.get('extra_challenge_seconds', 60)))}",
        reply_markup=scenario_management_menu(),
    )

@router.callback_query(lambda c: c.data.startswith("scenario_admin:edit:"))
async def scenario_edit_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _scenario_admin_allowed(callback):
        await callback.answer("دسترسی غیرمجاز.", show_alert=True)
        return
    sid = int(callback.data.rsplit(":", 1)[1])
    async with session_factory() as session:
        scenario = await session.get(Scenario, sid)
        if not scenario:
            await callback.answer("سناریو پیدا نشد.", show_alert=True)
            return
        current_roles_text = await _scenario_roles_text(session, sid)
    await state.clear()
    await state.set_state(ScenarioAdminState.name)
    await state.update_data(
        mode="edit",
        edit_id=sid,
        current_name=scenario.name_fa,
        current_description=scenario.description,
        current_turn_seconds=getattr(scenario, "turn_seconds", 120),
        current_challenge_seconds=getattr(scenario, "challenge_seconds", 60),
        current_extra_challenge_seconds=getattr(scenario, "extra_challenge_seconds", 60),
        current_roles_text=current_roles_text,
        current_voting_rules=getattr(scenario, "voting_rules", "{}"),
        current_vote_rule_input="50",
        challenge_mode=scenario.challenge_mode,
        current_vote_defense_threshold=getattr(scenario, "vote_defense_threshold", 2),
    )
    await callback.message.edit_text(f"✏️ ویرایش «{scenario.name_fa}»\n\nنام جدید را ارسال کنید یا - برای بدون تغییر:")
    await callback.answer()

@router.callback_query(lambda c: c.data.startswith("scenario_admin:delete:"))
async def scenario_delete_confirm_start(callback: CallbackQuery) -> None:
    if not await _scenario_admin_allowed(callback):
        await callback.answer("دسترسی غیرمجاز.", show_alert=True)
        return
    sid = int(callback.data.rsplit(":", 1)[1])
    async with session_factory() as session:
        scenario = await session.get(Scenario, sid)
    if not scenario:
        await callback.answer("سناریو پیدا نشد.", show_alert=True)
        return
    await callback.message.edit_text(
        f"⚠️ حذف سناریو «{scenario.name_fa}»\n\nترکیب نقش‌های آن نیز حذف می‌شود. ادامه می‌دهید؟",
        reply_markup=scenario_delete_confirm_keyboard(sid),
    )
    await callback.answer()

@router.callback_query(lambda c: c.data.startswith("scenario_admin:delete_confirm:"))
async def scenario_delete_confirm(callback: CallbackQuery) -> None:
    if not await _scenario_admin_allowed(callback):
        await callback.answer("دسترسی غیرمجاز.", show_alert=True)
        return
    sid = int(callback.data.rsplit(":", 1)[1])
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
    await callback.message.edit_text(result_text, reply_markup=scenario_management_menu())
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("notify:toggle:"))
async def notification_toggle(callback: CallbackQuery) -> None:
    if not callback.from_user or not callback.message:
        return
    field = callback.data.split(":")[-1]
    allowed = {"notify_game_result","notify_achievements","notify_rank_changes"}
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
