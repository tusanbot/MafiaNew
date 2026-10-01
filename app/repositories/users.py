from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import User

class UserRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        return (
            await self.session.execute(
                select(User).where(User.telegram_id == telegram_id)
            )
        ).scalar_one_or_none()

    async def upsert_from_telegram(
        self,
        telegram_id: int,
        username: str | None,
        first_name: str,
        last_name: str | None,
    ) -> User:
        user = await self.get_by_telegram_id(telegram_id)
        display_name = " ".join(x for x in [first_name, last_name] if x)
        if user is None:
            user = User(
                telegram_id=telegram_id,
                username=username,
                first_name=first_name,
                last_name=last_name,
                display_name=display_name,
            )
            self.session.add(user)
        else:
            user.username = username
            user.first_name = first_name
            user.last_name = last_name
            user.display_name = display_name
            user.is_active = True
        await self.session.flush()
        return user
