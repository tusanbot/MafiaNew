from sqlalchemy.ext.asyncio import AsyncSession
from aiogram.types import Chat

from app.repositories.groups import GroupRepository


async def sync_group(session: AsyncSession, chat: Chat):
    return await GroupRepository.upsert_from_chat(session, chat)
