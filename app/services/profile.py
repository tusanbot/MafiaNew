from sqlalchemy.ext.asyncio import AsyncSession
from app.repositories.users import UserRepository

async def sync_telegram_user(
    session: AsyncSession,
    telegram_id: int,
    username: str | None,
    first_name: str,
    last_name: str | None,
):
    user = await UserRepository(session).upsert_from_telegram(
        telegram_id, username, first_name, last_name
    )
    await session.commit()
    return user
