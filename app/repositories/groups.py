from sqlalchemy import select, update
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from aiogram.types import Chat

from app.db.models import Group, GroupSettings, User


class GroupRepository:
    @staticmethod
    async def upsert_from_chat(session: AsyncSession, chat: Chat) -> Group:
        # A Telegram group/supergroup Chat ID is the only valid source for
        # groups.telegram_id. Internal groups.id values must never enter here.
        if chat.type not in ("group", "supergroup"):
            raise ValueError("Only Telegram group/supergroup chats can be stored in groups.")
        if not isinstance(chat.id, int) or chat.id >= 0:
            raise ValueError("Invalid Telegram group chat ID.")

        result = await session.execute(select(Group).where(Group.telegram_id == chat.id))
        group = result.scalar_one_or_none()
        if group is None:
            group = Group(
                telegram_id=chat.id,
                title=chat.title or "",
                username=chat.username,
                type=chat.type,
            )
            session.add(group)
            await session.flush()
            session.add(GroupSettings(group_id=group.id))
        else:
            group.title = chat.title or group.title
            group.username = chat.username
            group.type = chat.type
            group.is_active = True
        await session.commit()
        return group

    @staticmethod
    async def get_by_telegram_id(session: AsyncSession, telegram_id: int) -> Group | None:
        result = await session.execute(select(Group).where(Group.telegram_id == telegram_id))
        return result.scalar_one_or_none()


    @staticmethod
    async def register(session: AsyncSession, group: Group, user_id: int) -> Group:
        # registered_by_user_id stores the internal users.id, never the Telegram ID.
        user = await session.get(User, user_id)
        if user is None:
            raise ValueError("ثبت‌کننده گروه در جدول users پیدا نشد.")

        registered_at = datetime.now(timezone.utc)
        await session.execute(
            update(Group)
            .where(Group.id == group.id)
            .values(
                is_active=True,
                registered_at=registered_at,
                registered_by_user_id=user.id,
            )
        )
        await session.commit()
        await session.refresh(group)
        return group
