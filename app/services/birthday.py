import asyncio
import logging
import random
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.types import Message
from sqlalchemy import select

from app.db.models import BirthdayAnnouncement, Game, GamePlayer, Group, User
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


def birthday_label(value) -> str:
    if not value:
        return "ثبت نشده"
    return value.strftime("%Y/%m/%d")


def is_birthday_today(value, now: datetime | None = None) -> bool:
    if not value:
        return False
    now = now or datetime.now(TEHRAN)
    return int(value.month) == int(now.month) and int(value.day) == int(now.day)


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

    name = tg_mention(user.telegram_id, user.display_name or user.first_name or "بازیکن")
    text = random.choice(BIRTHDAY_MESSAGES).format(name=name)
    try:
        photos = await bot.get_user_profile_photos(user.telegram_id, limit=1)
        if photos.total_count and photos.photos:
            await bot.send_photo(group.telegram_id, photos.photos[0][-1].file_id, caption=text)
        else:
            await bot.send_message(group.telegram_id, text)
        return True
    except Exception:
        logger.exception("Birthday announcement failed for group=%s user=%s", group.telegram_id, user.telegram_id)
        # Do not permanently suppress a birthday if Telegram send failed.
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


async def run_birthday_announcements(bot: Bot) -> None:
    """Run forever; safe to start once per bot process."""
    while True:
        try:
            now = datetime.now(TEHRAN)
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
                            # Membership lookup can fail for privacy/API reasons; avoid spamming unknown chats.
                            continue
                        await send_birthday_announcement(bot, group, user, birthday_key)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Birthday scheduler iteration failed")
        # Ten minutes is enough granularity and keeps database/API load low.
        await asyncio.sleep(600)
