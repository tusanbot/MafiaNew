from dataclasses import dataclass
from aiogram.types import ChatMemberAdministrator, ChatMemberOwner, ChatMemberRestricted
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Group
from app.repositories.groups import GroupRepository


@dataclass
class GroupRegistrationCheck:
    ok: bool
    problems: list[str]
    member_count: int = 0
    bot_is_admin: bool = False


REQUIRED_BOT_RIGHTS = (
    ("can_delete_messages", "حذف پیام‌ها"),
    ("can_pin_messages", "پین پیام"),
    ("can_restrict_members", "قفل/محدود کردن اعضا"),
)


async def check_group_registration(bot, chat_id: int) -> GroupRegistrationCheck:
    problems: list[str] = []

    try:
        member_count = await bot.get_chat_member_count(chat_id)
    except Exception:
        member_count = 0
        problems.append("تعداد اعضای گروه قابل دریافت نیست.")

    # Member-count restriction is temporarily disabled for testing groups.
    # Keep reading the count for diagnostics, but do not block registration on it.
    try:
        member_count = await bot.get_chat_member_count(chat_id)
    except Exception:
        member_count = 0


    bot_is_admin = False
    try:
        me = await bot.get_me()
        member = await bot.get_chat_member(chat_id, me.id)
        bot_is_admin = member.status in ("administrator", "creator")
        if not bot_is_admin:
            problems.append("ربات باید مدیر گروه باشد.")
        elif isinstance(member, ChatMemberAdministrator):
            for attr, label in REQUIRED_BOT_RIGHTS:
                if not bool(getattr(member, attr, False)):
                    problems.append(f"دسترسی «{label}» به ربات داده نشده است.")
        elif isinstance(member, ChatMemberOwner):
            pass
        else:
            problems.append("وضعیت مدیریتی ربات قابل تأیید نیست.")
    except Exception:
        problems.append("وضعیت مدیریتی ربات قابل بررسی نیست.")

    return GroupRegistrationCheck(
        ok=not problems,
        problems=problems,
        member_count=member_count,
        bot_is_admin=bot_is_admin,
    )


async def register_group(session: AsyncSession, chat, user_id: int) -> Group:
    group = await GroupRepository.upsert_from_chat(session, chat)
    return await GroupRepository.register(session, group, user_id)
