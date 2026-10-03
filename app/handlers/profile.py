from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
import os
import aiohttp
from sqlalchemy import func, select

from app.db.models import Achievement, Group, GroupSettings, Role, User, UserAchievement, UserRoleStat
from app.db.session import session_factory
from app.handlers.keyboards import main_menu, ranking_menu, profile_menu, profile_tags_keyboard
from app.services.profile import sync_telegram_user
from app.services.stats import achievement_progress, leaderboard, rank_for_score, rank_progress, user_achievements
from app.utils.text import tg_name

router = Router(name="profile")

class ProfileEditState(StatesGroup):
    name = State()
    tags = State()

async def _profile_text(session, user: User) -> str:
    position = (await session.scalar(select(func.count(User.id)).where(User.is_active.is_(True), User.score > user.score)) or 0) + 1
    rank, next_rank_score, rank_remaining = rank_progress(user.score)
    rank_hint = f"تا رتبه بعد: {rank_remaining} امتیاز" if next_rank_score is not None else "بالاترین رتبه"
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
        if earned:
            lines.append(f"{achievement.icon} {achievement.name_fa}  ✓  +{achievement.points}")
        else:
            progress = f"{current}/{target}" if target is not None else str(current)
            lines.append(f"🔒 {achievement.name_fa}  —  {progress}\n   {achievement.description}")
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

@router.callback_query(lambda c: c.data == "profile:achievements")
async def achievements_callback(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user:
        return
    async with session_factory() as session:
        user = (await session.execute(select(User).where(User.telegram_id == callback.from_user.id))).scalar_one_or_none()
        if not user:
            await callback.message.edit_text("هنوز پروفایلی برای شما ثبت نشده است.", reply_markup=profile_menu())
        else:
            await callback.message.edit_text(await _achievements_text(session, user), reply_markup=profile_menu())
    await callback.answer()

@router.callback_query(lambda c: c.data == "profile:score")
async def profile_score(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user: return
    async with session_factory() as session:
        user = await sync_telegram_user(session, callback.from_user)
        await session.commit()
        await callback.message.edit_text(await _profile_text(session, user), reply_markup=profile_menu())
    await callback.answer()

@router.callback_query(lambda c: c.data == "profile:rank")
async def profile_rank(callback: CallbackQuery) -> None:
    if not callback.message or not callback.from_user: return
    async with session_factory() as session:
        user = await sync_telegram_user(session, callback.from_user)
        position = (await session.scalar(select(func.count(User.id)).where(User.is_active.is_(True), User.score > user.score)) or 0) + 1
        rank, next_score, remaining = rank_progress(user.score)
        text = "🏆 رتبه شما\n\n" + f"رتبه: {rank}\nجایگاه: #{position}\nامتیاز: {user.score}\n"
        text += f"تا رتبه بعد: {remaining} امتیاز" if next_score is not None else "بالاترین رتبه را دارید."
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
    if not 2 <= len(value) <= 40:
        await message.answer("نام باید بین ۲ تا ۴۰ کاراکتر باشد.")
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

