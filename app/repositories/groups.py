from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from aiogram.types import Chat

from app.db.models import Group, GroupSettings


class GroupRepository:
    @staticmethod
    async def upsert_from_chat(session: AsyncSession, chat: Chat) -> Group:
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
