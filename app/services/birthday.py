import asyncio
import logging
import random
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.types import Message
from sqlalchemy import select

from app.db.models import BirthdayAnnouncement, BirthdayMessageTemplate, BirthdaySetting, Game, GamePlayer, Group, User
from app.db.session import session_factory
from app.utils.text import tg_mention

logger = logging.getLogger(__name__)
TEHRAN = ZoneInfo("Asia/Tehran")

BIRTHDAY_MESSAGES = (
    "🎂 تولدت مبارک {name}!\nامیدواریم سال جدید زندگیت پر از برد، حال خوب و اتفاق‌های قشنگ باشه. 🎉",
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
    """Parse YYYY/MM/DD, YYYY-MM-DD, MM/DD or MM-DD."""
    raw = _normalize_digits(value.strip()).replace(" ", "")
    for fmt in ("%Y/%m/%d", "%Y-%m-%d", "%m/%d", "%m-%d"):
        try:
            dt = datetime.strptime(raw, fmt)
            # Year 2000 is a neutral leap-safe storage year for recurring dates.
            if fmt in ("%m/%d", "%m-%d"):
                dt = dt.replace(year=2000)
            return dt
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
    return value.strftime("%Y/%m/%d")


def is_birthday_today(value, now: datetime | None = None) -> bool:
    if not value:
        return False
    now = now or datetime.now(TEHRAN)
    return int(value.month) == int(now.month) and int(value.day) == int(now.day)


async def _birthday_content():
    async with session_factory() as session:
        settings = await session.scalar(select(BirthdaySetting).where(BirthdaySetting.id == 1))
        templates = list((await session.execute(
            select(BirthdayMessageTemplate).where(BirthdayMessageTemplate.enabled.is_(True)).order_by(BirthdayMessageTemplate.id)
        )).scalars().all())
        return settings, templates


def _render_template(template: str, user: User) -> str:
    name = user.display_name or user.first_name or "بازیکن"
    mention = tg_mention(user.telegram_id, name)
    values = {
        "name": name,
        "first_name": user.first_name or name,
        "username": (user.username or "").lstrip("@"),
        "mention": mention,
        "user_id": str(user.telegram_id),
        "birthday": birthday_label(user.birthday),
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

    settings, templates = await _birthday_content()
    fallback = "🎂 تولدت مبارک {mention} عزیز! 🎉"
    template = random.choice(templates).text if templates else fallback
    text = _render_template(template, user)
    try:
        if settings and settings.enabled and settings.video_file_id:
            if len(text) <= 1024:\n                await bot.send_video(group.telegram_id, settings.video_file_id, caption=text, parse_mode="HTML")\n            else:\n                await bot.send_video(group.telegram_id, settings.video_file_id)\n                await bot.send_message(group.telegram_id, text, parse_mode="HTML")
        else:
            await bot.send_message(group.telegram_id, text)
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
    """Send birthday greetings once per day at 09:00 Asia/Tehran."""
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

