from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
import os
import aiohttp
import html
import json
from datetime import datetime, timedelta, timezone
from sqlalchemy import func, select

from app.db.models import Achievement, Group, GroupSettings, Role, User, UserAchievement, UserRoleStat, UserScoreHistory
from app.db.session import session_factory
from app.handlers.keyboards import main_menu, ranking_menu, profile_menu, profile_tags_keyboard
from app.utils.custom_emoji import custom_emoji_html
from app.services.profile import sync_telegram_user
from app.services.stats import achievement_progress, leaderboard, rank_for_score, rank_progress, user_achievements
from app.utils.text import tg_name
from app.services.rich_message import edit_rich_message, send_rich_message

router = Router(name="profile")


async def _profile_rich_html(session, user: User) -> str:
    position = (await session.scalar(select(func.count(User.id)).where(User.is_active.is_(True), User.score > user.score)) or 0) + 1
    rank, next_score, remaining = rank_progress(user.score)
    win_rate = (user.games_won / user.games_played * 100) if user.games_played else 0
    return (
        f"<h2>📊 امتیازات {tg_name(user.display_name or user.first_name or 'بازیکن')}</h2>"
        f"<table bordered striped compact><tr><th>مورد</th><th>مقدار</th></tr>"
        f"<tr><td>امتیاز</td><td><b>{int(user.score)}</b></td></tr>"
        f"<tr><td>سطح</td><td>{rank}</td></tr><tr><td>جایگاه</td><td>#{position}</td></tr>"
        f"<tr><td>بازی</td><td>{int(user.games_played)}</td></tr>"
        f"<tr><td>برد</td><td>{int(user.games_won)}</td></tr>"
        f"<tr><td>نرخ برد</td><td>{win_rate:.0f}%</td></tr></table>"
        f"<p>{('تا سطح بعد: ' + str(remaining) + ' امتیاز') if next_score is not None else 'بالاترین سطح را دارید.'}</p>"
        '<tg-button-row align="center"><tg-button type="callback_data" style="primary" data="profile:score">💰 امتیازات</tg-button><tg-button type="callback_data" style="success" data="profile:rank">🏆 رتبه</tg-button></tg-button-row>'
        '<tg-button-row align="center"><tg-button type="callback_data" data="menu:root">🏠 منوی اصلی</tg-button></tg-button-row>'
    )

async def _achievements_rich_html(session, user: User) -> str:
    rows = await achievement_progress(session, user)
    earned = sum(1 for _, ok, _, _ in rows if ok)
    body = []
    for achievement, is_earned, current, target in rows:
        description = (achievement.description or "برای این دستاورد هنوز توضیحی ثبت نشده است.").strip()
        if is_earned:
            body.append(
                f"<tr><td>{custom_emoji_html(achievement.custom_emoji_id, achievement.icon or '🏅')} {achievement.name_fa}</td><td>{description}</td><td>✅ +{achievement.points}</td></tr>"
            )
        else:
            progress = f"{current}/{target}" if target is not None else str(current)
            body.append(
                f"<tr><td>🔒 {achievement.name_fa}</td><td>{description}</td><td>{progress}</td></tr>"
            )
    table = '<table bordered striped compact><tr><th>دستاورد</th><th>توضیح</th><th>وضعیت</th></tr>' + ''.join(body) + '</table>' if body else '<p>هنوز دستاوردی ثبت نشده است.</p>'
    return (
        f'<h2>🏅 دستاوردها</h2><p>تعداد کسب‌شده: <b>{earned}</b></p>{table}'
        '<tg-button-row align="center"><tg-button type="callback_data" data="menu:root">🏠 منوی اصلی</tg-button></tg-button-row>'
    )


_PROFILE_COMMANDS = {"پروفایل", "profile", "/profile", "رتبه", "rank", "/rank", "ranking", "/ranking", "آمار", "stats", "/stats", "statistics", "/statistics"}

def _command_kind(text: str) -> str | None:
    value = " ".join((text or "").strip().lower().split())
    if value in {"پروفایل", "profile", "/profile"}: return "profile"
    if value in {"رتبه", "rank", "/rank", "ranking", "/ranking"}: return "rank"
    if value in {"آمار", "stats", "/stats", "statistics", "/statistics"}: return "stats"
    return None

async def _resolve_command_user(message: Message, session):
    target = message.reply_to_message.from_user if message.reply_to_message and message.reply_to_message.from_user else message.from_user
    if target is None: return None
    return await sync_telegram_user(session, target.id, target.username, target.first_name or "", target.last_name)

async def _user_position(session, user: User) -> int:
    return int((await session.scalar(select(func.count(User.id)).where(
        User.is_active.is_(True), User.games_played > 0, User.score > user.score
    )) or 0) + 1)

def _active_tag(user: User) -> str:
    key = (user.active_tag_key or "").strip()
    if not key: return "ندارد"
    raw = (user.tags or "").strip()
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                value = data.get(key)
                if isinstance(value, dict):
                    return f"{value.get('emoji', '')} {value.get('name') or value.get('name_fa') or key}".strip()
                if isinstance(value, str): return value
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and str(item.get("key", "")) == key:
                        return f"{item.get('emoji', '')} {item.get('name') or item.get('name_fa') or key}".strip()
        except Exception:
            pass
        for part in raw.split(","):
            if ":" in part:
                k, value = part.split(":", 1)
                if k.strip() == key: return value.strip()
    return key

async def _latest_achievement(session, user_id: int):
    return await session.scalar(select(Achievement).join(UserAchievement, UserAchievement.achievement_id == Achievement.id)
        .where(UserAchievement.user_id == user_id).order_by(UserAchievement.earned_at.desc()).limit(1))

async def _rank_history(session, user: User):
    now = datetime.now(timezone.utc)
    latest = await session.scalar(select(UserScoreHistory).where(UserScoreHistory.user_id == user.id)
        .order_by(UserScoreHistory.created_at.desc(), UserScoreHistory.id.desc()).limit(1))
    month_old = await session.scalar(select(UserScoreHistory).where(
        UserScoreHistory.user_id == user.id, UserScoreHistory.created_at <= now - timedelta(days=30)
    ).order_by(UserScoreHistory.created_at.desc(), UserScoreHistory.id.desc()).limit(1))
    return latest, month_old

async def _profile_rich_html_detailed(session, user: User) -> str:
    position = await _user_position(session, user)
    rank, _, remaining = rank_progress(int(user.score))
    win_rate = user.games_won / user.games_played * 100 if user.games_played else 0
    achievement = await _latest_achievement(session, user)
    latest, _ = await _rank_history(session, user)
    name = html.escape(tg_name(user.display_name or user.first_name or "بازیکن"), quote=False)
    tag = html.escape(_active_tag(user), quote=False)
    last_achievement = f"{achievement.icon or '🏅'} {html.escape(achievement.name_fa)}" if achievement else "هنوز دستاوردی فعال نشده"
    return (
        f"<h2>👤 پروفایل {name}</h2><table bordered striped compact>"
        "<tr><th>مورد</th><th>مقدار</th></tr>"
        f"<tr><td>سطح</td><td>{html.escape(rank)}</td></tr><tr><td>رتبه</td><td>#{position}</td></tr>"
        f"<tr><td>امتیاز</td><td><b>{int(user.score)}</b></td></tr><tr><td>بازی‌های انجام‌شده</td><td>{int(user.games_played)}</td></tr>"
        f"<tr><td>برد</td><td>{int(user.games_won)} ({win_rate:.1f}٪)</td></tr><tr><td>تگ فعال</td><td>{tag}</td></tr>"
        f"<tr><td>آخرین دستاورد فعال‌شده</td><td>{last_achievement}</td></tr>"
        f"<tr><td>برد متوالی</td><td>{int(user.win_streak)} | بهترین: {int(user.best_win_streak)}</td></tr></table>"
        f"<p>{('⏳ تا سطح بعد: ' + str(remaining) + ' امتیاز') if remaining else '👑 شما در بالاترین سطح هستید.'}</p>"
        f"<p>آخرین تغییر امتیاز: <b>{('+' if latest and latest.score_delta >= 0 else '') + str(latest.score_delta) if latest else '—'}</b></p>"
    )

async def _rank_rich_html(session, user: User) -> str:
    position = await _user_position(session, user)
    latest, month_old = await _rank_history(session, user)
    rank = rank_for_score(int(user.score))
    last_delta = f"{'+' if latest and latest.score_delta >= 0 else ''}{latest.score_delta}" if latest else "—"
    if month_old:
        change = int(month_old.rank_position or position) - position
        month_text = f"📈 +{change} رتبه" if change > 0 else (f"📉 {change} رتبه" if change < 0 else "➖ بدون تغییر")
    else:
        month_text = "⏳ هنوز سابقه ۳۰ روزه کافی ثبت نشده"
    name = html.escape(tg_name(user.display_name or user.first_name or "بازیکن"), quote=False)
    return (
        f"<h2>🏆 رتبه {name}</h2><table bordered striped compact><tr><th>مورد</th><th>مقدار</th></tr>"
        f"<tr><td>رتبه فعلی</td><td><b>#{position}</b></td></tr><tr><td>سطح</td><td>{html.escape(rank)}</td></tr>"
        f"<tr><td>امتیاز</td><td><b>{int(user.score)}</b></td></tr><tr><td>آخرین امتیاز کسب‌شده</td><td><b>{last_delta}</b></td></tr>"
        f"<tr><td>تغییر رتبه در ۳۰ روز</td><td>{month_text}</td></tr></table>"
        "<p>ℹ️ تغییر رتبه از روی آخرین سابقه ثبت‌شده در بازی‌ها محاسبه می‌شود.</p>"
    )

async def _stats_rich_html(session, user: User) -> str:
    games, wins = int(user.games_played), int(user.games_won)
    win_rate = wins / games * 100 if games else 0
    name = html.escape(tg_name(user.display_name or user.first_name or "بازیکن"), quote=False)
    role_rows = list((await session.execute(select(UserRoleStat, Role).join(Role, Role.id == UserRoleStat.role_id)
        .where(UserRoleStat.user_id == user.id).order_by(UserRoleStat.games.desc(), UserRoleStat.wins.desc()).limit(10))).all())
    role_table = ""
    if role_rows:
        rows = "".join(f"<tr><td>{html.escape(role.name_fa)}</td><td>{int(stat.games)}</td><td>{int(stat.wins)}</td><td>{(stat.wins/stat.games*100):.0f}٪</td></tr>" for stat, role in role_rows)
        role_table = "<h3>🎭 آمار نقش‌ها</h3><table bordered striped compact><tr><th>نقش</th><th>بازی</th><th>برد</th><th>برد٪</th></tr>" + rows + "</table>"
    return (
        f"<h2>📊 آمار کامل {name}</h2><table bordered striped compact><tr><th>شاخص</th><th>تعداد</th></tr>"
        f"<tr><td>🎮 تعداد بازی</td><td>{games}</td></tr><tr><td>🏆 تعداد برد</td><td>{wins}</td></tr>"
        f"<tr><td>📈 درصد برد</td><td>{win_rate:.1f}٪</td></tr><tr><td>🔵 برد شهروند</td><td>{int(user.citizen_wins)}</td></tr>"
        f"<tr><td>🔴 برد مافیا</td><td>{int(user.mafia_wins)}</td></tr><tr><td>🟣 برد مستقل</td><td>{int(user.independent_wins)}</td></tr>"
        f"<tr><td>⚔️ چالش‌های گرفته‌شده</td><td>{int(user.challenges)}</td></tr><tr><td>🔥 بیشترین برد پیاپی</td><td>{int(user.best_win_streak)}</td></tr>"
        f"<tr><td>🎯 شات موفق</td><td>{int(user.kills)}</td></tr><tr><td>🩺 نجات موفق</td><td>{int(user.saves)}</td></tr>"
        f"<tr><td>🔎 تحقیقات موفق</td><td>{int(user.investigation_hits)}</td></tr><tr><td>🎯 رأی درست علیه مافیا</td><td>{int(user.correct_votes)}</td></tr>"
        f"<tr><td>🛡 بقا</td><td>{int(user.games_survived)}</td></tr><tr><td>🏅 دستاوردها</td><td>{int(user.achievements_count)}</td></tr></table>{role_table}"
    )

@router.message(lambda m: _command_kind(m.text or "") is not None)
async def text_profile_rank_stats(message: Message) -> None:
    kind = _command_kind(message.text or "")
    if not kind: return
    if not message.from_user and not (message.reply_to_message and message.reply_to_message.from_user): return
    async with session_factory() as session:
        user = await _resolve_command_user(message, session)
        if not user: return
        await session.commit()
        try:
            content = await (_profile_rich_html_detailed(session, user) if kind == "profile" else _rank_rich_html(session, user) if kind == "rank" else _stats_rich_html(session, user))
            await send_rich_message(message.bot, message.chat.id, content, reply_parameters={"message_id": message.message_id})
        except Exception:
            if kind == "profile":
                text = f"👤 پروفایل {tg_name(user.display_name or user.first_name or 'بازیکن')}\nسطح: {rank_for_score(user.score)}\nرتبه: #{await _user_position(session, user)}\nامتیاز: {user.score}\nبازی: {user.games_played}\nبرد: {user.games_won}\nتگ فعال: {_active_tag(user)}"
            elif kind == "rank":
                latest, month_old = await _rank_history(session, user); pos = await _user_position(session, user); change = "—" if not month_old else str(int(month_old.rank_position or pos) - pos)
                text = f"🏆 رتبه {tg_name(user.display_name or user.first_name or 'بازیکن')}\nرتبه: #{pos}\nامتیاز: {user.score}\nآخرین امتیاز: {latest.score_delta if latest else '—'}\nتغییر رتبه ۳۰ روزه: {change}"
            else:
                text = f"📊 آمار {tg_name(user.display_name or user.first_name or 'بازیکن')}\nبازی: {user.games_played}\nبرد: {user.games_won}\nبرد٪: {(user.games_won/user.games_played*100 if user.games_played else 0):.1f}%\nشهروند: {user.citizen_wins}\nمافیا: {user.mafia_wins}\nمستقل: {user.independent_wins}\nچالش: {user.challenges}\nبهترین برد پیاپی: {user.best_win_streak}"
            await message.answer(text, reply_to_message_id=message.message_id)


class ProfileEditState(StatesGroup):
    name = State()
    tags = State()

async def _profile_text(session, user: User) -> str:
    position = (await session.scalar(select(func.count(User.id)).where(User.is_active.is_(True), User.score > user.score)) or 0) + 1
    rank, next_rank_score, rank_remaining = rank_progress(user.score)
    rank_hint = f"تا سطح بعد: {rank_remaining} امتیاز" if next_rank_score is not None else "بالاترین رتبه"
    win_rate = (user.games_won / user.games_played * 100) if user.games_played else 0
    role_rows = list((await session.execute(
        select(UserRoleStat, Role).join(Role, Role.id == UserRoleStat.role_id)
        .where(UserRoleStat.user_id == user.id)
        .order_by(UserRoleStat.games.desc(), UserRoleStat.wins.desc())
        .limit(5)
    )).all())
    role_lines = ["", "🎭 آمار نقش‌ها"]
    if role_rows:
        for stat, role in role_rows:
            role_rate = (stat.wins / stat.games * 100) if stat.games else 0
            extras = []
            if stat.kills: extras.append(f"شات {stat.kills}")
            if stat.saves: extras.append(f"نجات {stat.saves}")
            if stat.investigations: extras.append(f"تحقیق {stat.investigations}")
            detail = " • " + " • ".join(extras) if extras else ""
            role_lines.append(f"• {role.name_fa}: {stat.games} بازی | {stat.wins} برد | {role_rate:.0f}%{detail}")
    else:
        role_lines.append("هنوز آمار نقشی ثبت نشده است.")
    return (
        "👤 پروفایل بازیکن\n\n"
        f"نام: {tg_name(user.display_name or user.first_name or 'بازیکن')}\n"
        f"رتبه: {rank}  •  جایگاه: #{position}\n"
        f"📊 {rank_hint}\n"
        f"امتیاز: {user.score}\n\n"
        f"🎮 بازی‌ها: {user.games_played}\n"
        f"🏆 بردها: {user.games_won}\n"
        f"📈 نرخ برد: {win_rate:.1f}%\n"
        f"🔴 برد مافیا: {user.mafia_wins}\n"
        f"🔵 برد شهروند: {user.citizen_wins}\n"
        f"🟣 برد مستقل: {user.independent_wins}\n\n"
        f"⚔️ چالش‌ها: {user.challenges}  |  پذیرفته‌شده: {user.challenges_accepted}\n"
        f"🎯 شات: {user.kills}  |  نجات: {user.saves}\n"
        f"🔎 تحقیقات: {user.investigations}  |  موفق: {user.investigation_hits}\n"
        f"🗳 رأی درست علیه مافیا: {user.correct_votes}\n"
        f"⚔️ فیس‌آف: {user.faceoffs}  |  برد: {user.faceoff_wins}\n"
        f"☠️ بقا: {user.games_survived}/{user.games_played}  |  کیک: {user.kicks}\n"
        f"🔥 برد متوالی: {user.win_streak}  |  بهترین: {user.best_win_streak}\n"
        f"🏅 دستاوردها: {user.achievements_count}\n"
        + "\n".join(role_lines)
    )

@router.message(Command("profile"))
async def profile_handler(message: Message) -> None:
    if message.chat.type != "private" or not message.from_user:
        return
    tg = message.from_user
    async with session_factory() as session:
        db_user = await sync_telegram_user(session, tg.id, tg.username, tg.first_name or "", tg.last_name)
        await session.commit()
        await message.answer("👤 پروفایل شما\n\nبخش موردنظر را انتخاب کنید.", reply_markup=profile_menu())

@router.callback_query(lambda c: c.data == "menu:profile")
async def profile_menu_handler(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    async with session_factory() as session:
        tg = callback.from_user
        user = await sync_telegram_user(session, tg.id, tg.username, tg.first_name or "", tg.last_name)
        await session.commit()
        await callback.message.edit_text("👤 پروفایل شما\n\nبخش موردنظر را انتخاب کنید.", reply_markup=profile_menu())
    await callback.answer()

@router.message(Command("ranking"))
async def ranking_command(message: Message) -> None:
    if message.chat.type != "private":
        return
    async with session_factory() as session:
        await _render_ranking(message, session, "all")

async def _rich_ranking_html(rows, kind: str, custom_emoji: bool = False) -> str:
    """Build a native Telegram Rich Message for the ranking screen.

    Rich Messages are sent through Bot API 10.1+ and rendered as a real table,
    not as a Unicode/monospace imitation. Custom Emoji is opt-in; the caller
    falls back to the normal emoji when Telegram rejects the custom emoji.
    """
    title = {
        "all": "رتبه‌بندی بازیکنان",
        "mafia": "برترین‌های مافیا",
        "citizen": "برترین‌های شهروند",
    }.get(kind, "رتبه‌بندی")

    custom_emoji_id = os.getenv("MAFIA_CUSTOM_EMOJI_ID", "").strip()
    trophy = (
        f'<tg-emoji emoji-id="{custom_emoji_id}">🏆</tg-emoji>'
        if custom_emoji and custom_emoji_id else "🏆"
    )

    rows_html = []
    medals = ("🥇", "🥈", "🥉")
    for i, user in enumerate(rows, 1):
        name = tg_name(user.display_name or user.first_name or "بازیکن")
        name = (
            name.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )
        rank_icon = medals[i - 1] if i <= 3 else str(i)
        rows_html.append(
            f"<tr><td align=\"center\">{rank_icon}</td>"
            f"<td>{name}</td>"
            f"<td align=\"center\"><b>{int(user.score)}</b></td>"
            f"<td align=\"center\">{int(user.games_played)}</td>"
            f"<td align=\"center\">{int(user.games_won)}</td>"
            f"<td align=\"center\">{(user.games_won / user.games_played * 100):.0f}%</td></tr>"
        )

    if not rows_html:
        table = "<p>هنوز بازی کاملی برای رتبه‌بندی ثبت نشده است.</p>"
    else:
        table = (
            '<table bordered striped compact>'
            "<tr><th>#</th><th>بازیکن</th><th>امتیاز</th>"
            "<th>بازی</th><th>برد</th><th>برد٪</th></tr>"
            + "".join(rows_html)
            + "</table>"
        )

    return (
        f"<h2>{trophy} {title}</h2>"
        "<p>🏅 رتبه‌بندی بر اساس امتیاز و عملکرد ثبت‌شده در بازی‌ها</p>"
        f"{table}"
        "<p>برای دیدن یک جدول دیگر، معیار موردنظر را انتخاب کن:</p>"
        '<tg-button-row align="center">'
        '<tg-button type="callback_data" style="primary" data="ranking:players">🏆 همه بازیکنان</tg-button>'
        '<tg-button type="callback_data" style="primary" data="ranking:mafia">🔴 مافیا</tg-button>'
        '<tg-button type="callback_data" style="success" data="ranking:citizen">🔵 شهروند</tg-button>'
        '</tg-button-row>'
        '<tg-button-row align="center">'
        '<tg-button type="callback_data" data="menu:root">↩️ بازگشت</tg-button>'
        '</tg-button-row>'
    )


async def _send_rich_ranking(target, rows, kind: str, *, edit: bool = False, custom_emoji: bool = False) -> bool:
    """Send/edit a Rich Message using the Bot API directly.

    aiogram 3.22 does not yet expose every Bot API 10.3 Rich Message field as
    high-level types, so this small transport keeps the rest of the handlers
    fully native to aiogram.
    """
    bot = target.bot if hasattr(target, "bot") else target
    message = target.message if hasattr(target, "message") and target.message else target
    token = bot.token
    method = "editMessageText" if edit else "sendRichMessage"
    payload = {
        "chat_id": int(message.chat.id),
        "rich_message": {
            "html": await _rich_ranking_html(rows, kind, custom_emoji=custom_emoji),
            "is_rtl": True,
        },
    }
    if edit:
        payload["message_id"] = int(message.message_id)

    url = f"https://api.telegram.org/bot{token}/{method}"
    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=timeout) as http:
        async with http.post(url, json=payload) as response:
            data = await response.json(content_type=None)
            if not response.ok or not data.get("ok"):
                raise RuntimeError(data.get("description") or f"Telegram API {response.status}")
            return True


async def _render_ranking(target, session, kind: str):
    team = kind if kind in {"mafia", "citizen"} else None
    rows = await leaderboard(session, 10, team)

    # Custom Emoji is intentionally opt-in. The Premium capability itself is
    # detected by the API response: if Telegram rejects the custom emoji, we
    # immediately resend/edit the same ranking with ordinary emoji.
    custom_emoji_enabled = False
    if isinstance(target, Message) and target.chat.type in {"group", "supergroup"}:
        group_id = await session.scalar(
            select(Group.id).where(Group.telegram_id == target.chat.id)
        )
        group_settings = (
            await session.scalar(select(GroupSettings).where(GroupSettings.group_id == group_id))
            if group_id is not None else None
        )
        custom_emoji_enabled = bool(group_settings and group_settings.custom_emoji)
    elif hasattr(target, "message") and target.message and target.message.chat.type in {"group", "supergroup"}:
        group_id = await session.scalar(
            select(Group.id).where(Group.telegram_id == target.message.chat.id)
        )
        group_settings = (
            await session.scalar(select(GroupSettings).where(GroupSettings.group_id == group_id))
            if group_id is not None else None
        )
        custom_emoji_enabled = bool(group_settings and group_settings.custom_emoji)

    try:
        await _send_rich_ranking(
            target,
            rows,
            kind,
            edit=not isinstance(target, Message),
            custom_emoji=custom_emoji_enabled,
        )
    except Exception:
        # A failed Rich Message must never break ranking. Retry without
        # custom emoji first, then fall back to a standard HTML message.
        try:
            await _send_rich_ranking(
                target,
                rows,
                kind,
                edit=not isinstance(target, Message),
                custom_emoji=False,
            )
        except Exception:
            title = {
                "all": "🏆 رتبه‌بندی بازیکنان",
                "mafia": "🔴 برترین‌های مافیا",
                "citizen": "🔵 برترین‌های شهروند",
            }.get(kind, "🏆 رتبه‌بندی")
            lines = [f"<b>{title}</b>", ""]
            if rows:
                for i, user in enumerate(rows, 1):
                    name = tg_name(user.display_name or user.first_name or "بازیکن")
                    lines.append(
                        f"{i}. {name} — <b>{int(user.score)}</b> امتیاز — "
                        f"{int(user.games_won)}/{int(user.games_played)} برد"
                    )
            else:
                lines.append("هنوز بازی کاملی برای رتبه‌بندی ثبت نشده است.")
            if isinstance(target, Message):
                await target.answer("\n".join(lines), parse_mode="HTML", reply_markup=ranking_menu())
            else:
                await target.message.edit_text("\n".join(lines), parse_mode="HTML", reply_markup=ranking_menu())


@router.callback_query(lambda c: c.data == "menu:ranking")
async def ranking_menu_handler(callback: CallbackQuery) -> None:
    if not callback.message:
        return
    async with session_factory() as session:
        await _render_ranking(callback, session, "all")
    await callback.answer()

@router.callback_query(lambda c: c.data.startswith("ranking:"))
async def ranking_callback(callback: CallbackQuery) -> None:
    if not callback.message:
        return
    kind = callback.data.split(":", 1)[1]
    if kind not in {"players", "mafia", "citizen"}:
        await callback.answer()
        return
    kind = {"players": "all"}.get(kind, kind)
    async with session_factory() as session:
        await _render_ranking(callback, session, kind)
    await callback.answer()

async def _achievements_text(session, user: User) -> str:
    rows = await achievement_progress(session, user)
    lines = ["🏅 دستاوردها", f"تعداد کسب‌شده: {user.achievements_count}", ""]
    for achievement, earned, current, target in rows:
        description = (achievement.description or "برای این دستاورد هنوز توضیحی ثبت نشده است.").strip()
        if earned:
            lines.append(f"{custom_emoji_html(achievement.custom_emoji_id, achievement.icon or "🏅")} {achievement.name_fa}  ✓  +{achievement.points}\n   {description}")
        else:
            progress = f"{current}/{target}" if target is not None else str(current)
            lines.append(f"🔒 {achievement.name_fa}  —  {progress}\n   {description}")
    return "\n".join(lines)

@router.message(Command("achievements"))
async def achievements_command(message: Message) -> None:
    if message.chat.type != "private" or not message.from_user:
        return
    async with session_factory() as session:
        user = (await session.execute(select(User).where(User.telegram_id == message.from_user.id))).scalar_one_or_none()
        if not user:
            await message.answer("هنوز پروفایلی برای شما ثبت نشده است.")
            return
        await message.answer(await _achievements_text(session, user), reply_markup=profile_menu())

@router.callback_query(lambda c: c.data in {"profile:achievements", "menu:achievements"})
async def achievements_callback(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    async with session_factory() as session:
        user = (await session.execute(select(User).where(User.telegram_id == callback.from_user.id))).scalar_one_or_none()
        if not user:
            await callback.message.edit_text("هنوز پروفایلی برای شما ثبت نشده است.", reply_markup=main_menu())
        else:
            try:
                await edit_rich_message(
                    callback.bot,
                    callback.message.chat.id,
                    callback.message.message_id,
                    await _achievements_rich_html(session, user),
                )
            except Exception:
                await callback.message.edit_text(
                    await _achievements_text(session, user),
                    reply_markup=main_menu() if callback.data == "menu:achievements" else profile_menu(),
                    parse_mode="HTML",
                )
    await callback.answer()

@router.callback_query(lambda c: c.data == "profile:score")
async def profile_score(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user: return
    async with session_factory() as session:
        user = await sync_telegram_user(session, callback.from_user.id, callback.from_user.username, callback.from_user.first_name or "", callback.from_user.last_name)
        await session.commit()
        try:
            await edit_rich_message(callback.bot, callback.message.chat.id, callback.message.message_id, await _profile_rich_html(session, user))
        except Exception:
            await callback.message.edit_text(await _profile_text(session, user), reply_markup=profile_menu())
    await callback.answer()

@router.callback_query(lambda c: c.data == "profile:rank")
async def profile_rank(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user: return
    async with session_factory() as session:
        user = await sync_telegram_user(session, callback.from_user.id, callback.from_user.username, callback.from_user.first_name or "", callback.from_user.last_name)
        position = (await session.scalar(select(func.count(User.id)).where(User.is_active.is_(True), User.score > user.score)) or 0) + 1
        rank, next_score, remaining = rank_progress(user.score)
        text = "🏆 سطح شما\n\n" + f"سطح: {rank}\nجایگاه: #{position}\nامتیاز: {user.score}\n"
        text += f"تا سطح بعد: {remaining} امتیاز" if next_score is not None else "بالاترین سطح را دارید."
        rich_html = (
            f'<h2>🏆 سطح شما</h2>'
            f'<table bordered striped compact><tr><th>مورد</th><th>مقدار</th></tr>'
            f'<tr><td>سطح</td><td>{rank}</td></tr>'
            f'<tr><td>جایگاه</td><td>#{position}</td></tr>'
            f'<tr><td>امتیاز</td><td><b>{int(user.score)}</b></td></tr></table>'
            f'<p>{("تا سطح بعد: " + str(remaining) + " امتیاز") if next_score is not None else "بالاترین سطح را دارید."}</p>'
            '<tg-button-row align="center">'
            '<tg-button type="callback_data" data="profile:score">💰 امتیازات</tg-button>'
            '<tg-button type="callback_data" style="primary" data="menu:root">🏠 منوی اصلی</tg-button>'
            '</tg-button-row>'
        )
        try:
            await edit_rich_message(callback.bot, callback.message.chat.id, callback.message.message_id, rich_html)
        except Exception:
            await callback.message.edit_text(text, reply_markup=profile_menu())
    await callback.answer()

@router.callback_query(lambda c: c.data == "profile:name")
async def profile_name_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.message:
        return
    await state.set_state(ProfileEditState.name)
    await callback.message.edit_text("✏️ نام نمایشی جدید را ارسال کنید.\nبرای انصراف /cancel را بفرستید.")
    await callback.answer()

@router.message(ProfileEditState.name)
async def profile_name_save(message: Message, state: FSMContext) -> None:
    if not message.from_user or message.chat.type != "private":
        return
    value = (message.text or "").strip()
    if value == "/cancel":
        await state.clear()
        await message.answer("ویرایش نام لغو شد.", reply_markup=profile_menu())
        return
    import re
    if not 2 <= len(value) <= 40:
        await message.answer("نام باید بین ۲ تا ۴۰ حرف باشد.")
        return
    # Display names are intentionally limited to Persian letters and spaces.
    # Digits, Latin/Arabic letters, emoji, punctuation and symbols are rejected.
    if not re.fullmatch(r"[آابپتثجچحخدذرزژسشصضطظعغفقکگلمنوهی‌ ]+", value) or not re.search(r"[آابپتثجچحخدذرزژسشصضطظعغفقکگلمنوهی]", value):
        await message.answer("❌ نام فقط باید شامل حروف فارسی باشد؛ عدد، حروف انگلیسی، اموجی و علامت مجاز نیست.")
        return
    async with session_factory() as session:
        user = await sync_telegram_user(session, message.from_user.id, message.from_user.username, message.from_user.first_name or "", message.from_user.last_name)
        user.name_base = value
        user.display_name_custom = True
        tag = None
        if user.active_tag_key:
            tag = await session.scalar(select(Achievement).where(Achievement.key == user.active_tag_key))
        user.display_name = f"{tag.tag_emoji} {value}".strip() if tag and tag.tag_emoji else value
        await session.commit()
    await state.clear()
    await message.answer("✅ نام نمایشی ذخیره شد.", reply_markup=profile_menu())

@router.callback_query(lambda c: c.data == "profile:tags")
async def profile_tags_start(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    async with session_factory() as session:
        user = await sync_telegram_user(session, callback.from_user.id, callback.from_user.username, callback.from_user.first_name or "", callback.from_user.last_name)
        tags = list((await session.execute(
            select(Achievement).join(UserAchievement, UserAchievement.achievement_id == Achievement.id)
            .where(UserAchievement.user_id == user.id, Achievement.tag_key.is_not(None))
            .order_by(Achievement.id)
        )).scalars().all())
        await callback.message.edit_text(
            "🏷️ تگ‌های قابل انتخاب\n\nهر تگ با باز کردن دستاورد مربوطه آزاد می‌شود. یکی را انتخاب کن تا ابتدای نامت نمایش داده شود.",
            reply_markup=profile_tags_keyboard(tags, user.active_tag_key),
        )
    await callback.answer()

@router.callback_query(lambda c: c.data and c.data.startswith("profile:tag:"))
async def profile_tag_select(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    key = callback.data.split(":", 2)[2]
    async with session_factory() as session:
        user = await sync_telegram_user(session, callback.from_user.id, callback.from_user.username, callback.from_user.first_name or "", callback.from_user.last_name)
        if key == "clear":
            user.active_tag_key = None
            user.display_name = user.name_base or user.display_name
            await session.commit()
        else:
            achievement = await session.scalar(select(Achievement).where(Achievement.key == key))
            earned = await session.scalar(select(UserAchievement.id).where(UserAchievement.user_id == user.id, UserAchievement.achievement_id == achievement.id)) if achievement else None
            if not achievement or not achievement.tag_key or not earned:
                await callback.answer("این تگ هنوز برای شما آزاد نشده است.", show_alert=True)
                return
            user.active_tag_key = achievement.tag_key
            base = user.name_base or user.display_name
            user.display_name = f"{achievement.tag_emoji} {base}".strip() if achievement.tag_emoji else base
            await session.commit()
        tags = list((await session.execute(
            select(Achievement).join(UserAchievement, UserAchievement.achievement_id == Achievement.id)
            .where(UserAchievement.user_id == user.id, Achievement.tag_key.is_not(None))
            .order_by(Achievement.id)
        )).scalars().all())
        await callback.message.edit_text("🏷️ تگ‌های قابل انتخاب", reply_markup=profile_tags_keyboard(tags, user.active_tag_key))
    await callback.answer("تگ فعال به‌روزرسانی شد.")

