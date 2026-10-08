import asyncio
import logging
import random
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.types import Message
from sqlalchemy import select

from app.db.models import BirthdayAnnouncement, BirthdayMessageTemplate, BirthdaySetting, Game, GamePlayer, Group, GroupSettings, User
from app.db.session import session_factory
from app.utils.text import tg_mention

logger = logging.getLogger(__name__)
TEHRAN = ZoneInfo("Asia/Tehran")

BIRTHDAY_MESSAGES = (
    "╔══════════════════════╗\n      🎂 پرونده ویژه\n╚══════════════════════╝\n\n🚨 یک اتفاق مهم در شهر افتاده!\n\nامروز روز تولد\n🎩 {mention}\nاست.\n\n🎉 شهروندان و مافیا، برای چند لحظه\nسلاح‌ها را زمین می‌گذارند...\n\n🥳 تولدت مبارک {mention} عزیز!\n\n🎁 برات یک سال پر از برد،\nسناریوهای جذاب و بازی‌های خفن\nآرزو می‌کنیم.\n\n🍰 امیدواریم امسال همیشه\nدر سمت برنده‌های بازی باشی!\n\n━━━━━━━━━━━━━━━━━━\n🎭 Mafia Nights\n━━━━━━━━━━━━━━━━━━",
    "🥳 امروز روز توئه {name}!\nاز طرف بچه‌های مافیا: تولدت مبارک و همیشه خوشحال و موفق باشی! 🎁",
    "🎈 یک سال دیگه هم گذشت و هنوز از دستت خلاص نشدیم {name}! 😄\nتولدت مبارک؛ سال فوق‌العاده‌ای برات آرزو می‌کنیم. 🎂",
    "🎉 تولدت مبارک {name}!\nامروز رأی‌گیری ممنوع؛ فقط تبریک و کیک! 🍰 امیدواریم همیشه بدرخشی.",
    "💐 بهترین آرزوها برای {name} در روز تولدش!\nتنت سالم، دلت شاد و بازی‌هات پر از برد. 🎂",
)


def _normalize_digits(value: str) -> str:
    return str(value or "").translate(str.maketrans(
        "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
        "01234567890123456789",
    ))


def parse_birthday(value: str):
    """Parse YYYY/MM/DD or a Persian-style DD/MM recurring birthday."""
    raw = _normalize_digits(value.strip()).replace(" ", "")
    for fmt in ("%Y/%m/%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue

    # For a recurring birthday without a year, use day/month because this is
    # the natural format used by Persian users (e.g. 5/10 = 5 October).
    for fmt in ("%d/%m", "%d-%m"):
        try:
            return datetime.strptime(raw, fmt).replace(year=2000)
        except ValueError:
            continue
    return None


async def get_telegram_profile_birthday(bot: Bot, telegram_id: int):
    """Read a visible Telegram profile birthday through Bot API getChat."""
    try:
        chat = await bot.get_chat(telegram_id)
        birthdate = getattr(chat, "birthdate", None)
        if not birthdate:
            return None
        day = int(getattr(birthdate, "day", 0) or 0)
        month = int(getattr(birthdate, "month", 0) or 0)
        year = int(getattr(birthdate, "year", 2000) or 2000)
        if not 1 <= month <= 12 or not 1 <= day <= 31:
            return None
        return datetime(year, month, day)
    except Exception:
        return None


async def get_effective_birthday(bot: Bot, user: User):
    """Prefer the bot profile value, then a visible Telegram profile birthday."""
    if user.birthday:
        return user.birthday, "ربات"
    birthday = await get_telegram_profile_birthday(bot, user.telegram_id)
    if birthday:
        return birthday, "پروفایل تلگرام"
    return None, None


def birthday_label(value) -> str:
    if not value:
        return "ثبت نشده"
    # Year 2000 is the internal sentinel for a recurring birthday entered
    # without a year; do not expose that implementation detail to the user.
    if int(value.year) == 2000:
        return value.strftime("%d/%m")
    return value.strftime("%Y/%m/%d")


def is_birthday_today(value, now: datetime | None = None) -> bool:
    if not value:
        return False
    now = now or datetime.now(TEHRAN)
    return int(value.month) == int(now.month) and int(value.day) == int(now.day)


async def _birthday_content(group: Group):
    async with session_factory() as session:
        group_settings = await session.scalar(select(GroupSettings).where(GroupSettings.group_id == group.id))
        settings = await session.scalar(select(BirthdaySetting).where(BirthdaySetting.id == 1))
        templates = list((await session.execute(
            select(BirthdayMessageTemplate).where(BirthdayMessageTemplate.enabled.is_(True)).order_by(BirthdayMessageTemplate.id)
        )).scalars().all())
        return group_settings, settings, templates


def _render_template(template: str, user: User) -> str:
    name = user.display_name or user.first_name or "بازیکن"
    mention = tg_mention(user.telegram_id, name)
    age = ""
    if user.birthday and int(user.birthday.year) != 2000:
        today = datetime.now(TEHRAN)
        age = str(max(0, today.year - int(user.birthday.year) - ((today.month, today.day) < (int(user.birthday.month), int(user.birthday.day)))))
    values = {
        "name": name,
        "first_name": user.first_name or name,
        "username": (user.username or "").lstrip("@"),
        "mention": mention,
        "user_id": str(user.telegram_id),
        "birthday": birthday_label(user.birthday),
        "age": age,
    }
    class SafeDict(dict):
        def __missing__(self, key):
            return "{" + key + "}"
    try:
        return str(template or "").format_map(SafeDict(values))
    except Exception:
        return str(template or "")


async def send_birthday_announcement(bot: Bot, group: Group, user: User, birthday_key: str) -> bool:
    async with session_factory() as session:
        existing = await session.scalar(select(BirthdayAnnouncement.id).where(
            BirthdayAnnouncement.group_id == group.id,
            BirthdayAnnouncement.user_id == user.id,
            BirthdayAnnouncement.birthday_key == birthday_key,
        ))
        if existing:
            return False
        session.add(BirthdayAnnouncement(
            group_id=group.id,
            user_id=user.id,
            birthday_key=birthday_key,
        ))
        await session.commit()

    group_settings, settings, templates = await _birthday_content(group)
    if group_settings and not group_settings.birthday_enabled:
        return False
    fallback = BIRTHDAY_MESSAGES[0]
    template = user.birthday_message or (group_settings.birthday_default_message if group_settings and group_settings.birthday_default_message else (random.choice(templates).text if templates else fallback))
    text = _render_template(template, user)
    media_type = user.birthday_media_type
    media_file_id = user.birthday_media_file_id
    if not media_file_id and group_settings and group_settings.birthday_media_enabled:
        media_type = group_settings.birthday_media_type
        media_file_id = group_settings.birthday_media_file_id
    if not media_file_id and group_settings and group_settings.birthday_media_enabled and settings and settings.enabled and settings.video_file_id:
        media_type, media_file_id = "video", settings.video_file_id
    try:
        if media_file_id and media_type == "photo":
            if len(text) <= 1024:
                await bot.send_photo(group.telegram_id, media_file_id, caption=text, parse_mode="HTML")
            else:
                await bot.send_photo(group.telegram_id, media_file_id)
                await bot.send_message(group.telegram_id, text, parse_mode="HTML")
        elif media_file_id and media_type == "video":
            if len(text) <= 1024:
                await bot.send_video(group.telegram_id, media_file_id, caption=text, parse_mode="HTML")
            else:
                await bot.send_video(group.telegram_id, media_file_id)
                await bot.send_message(group.telegram_id, text, parse_mode="HTML")
        else:
            await bot.send_message(group.telegram_id, text, parse_mode="HTML")
        return True
    except Exception:
        logger.exception("Birthday announcement failed for group=%s user=%s", group.telegram_id, user.telegram_id)
        async with session_factory() as session:
            row = await session.scalar(select(BirthdayAnnouncement).where(
                BirthdayAnnouncement.group_id == group.id,
                BirthdayAnnouncement.user_id == user.id,
                BirthdayAnnouncement.birthday_key == birthday_key,
            ))
            if row:
                await session.delete(row)
                await session.commit()
        return False


async def process_birthday_announcements(bot: Bot, now: datetime | None = None) -> None:
    now = now or datetime.now(TEHRAN)
    birthday_key = now.strftime("%Y-%m-%d")
    async with session_factory() as session:
        users = list((await session.execute(
            select(User).where(User.birthday.is_not(None), User.is_active.is_(True))
        )).scalars().all())
        for user in users:
            if not is_birthday_today(user.birthday, now):
                continue
            groups = list((await session.execute(
                select(Group).join(Game, Game.group_id == Group.id)
                .join(GamePlayer, GamePlayer.game_id == Game.id)
                .where(
                    GamePlayer.user_id == user.id,
                    Group.is_active.is_(True),
                ).distinct()
            )).scalars().all())
            for group in groups:
                try:
                    member = await bot.get_chat_member(group.telegram_id, user.telegram_id)
                    if getattr(member, "status", None) in {"left", "kicked"}:
                        continue
                except Exception:
                    continue
                await send_birthday_announcement(bot, group, user, birthday_key)


async def run_birthday_announcements(bot: Bot) -> None:
    """Send birthday greetings at 09:00 Asia/Tehran and recover after restarts."""
    # Run once immediately so a restart after 09:00 does not skip today's
    # birthdays. BirthdayAnnouncement's unique key prevents duplicates.
    try:
        await process_birthday_announcements(bot, datetime.now(TEHRAN))
    except Exception:
        logger.exception("Initial birthday announcement pass failed.")
    while True:
        try:
            now = datetime.now(TEHRAN)
            target = now.replace(hour=9, minute=0, second=0, microsecond=0)
            if target <= now:
                from datetime import timedelta
                target += timedelta(days=1)
            await asyncio.sleep(max(1, (target - now).total_seconds()))
            await process_birthday_announcements(bot, datetime.now(TEHRAN))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Birthday scheduler failed; retrying on the next scheduled run.")

