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
        telegram_name = " ".join(x for x in [first_name, last_name] if x)
        if user is None:
            user = User(
                telegram_id=telegram_id,
                username=username,
                first_name=first_name,
                last_name=last_name,
                display_name=telegram_name,
                name_base=telegram_name,
            )
            self.session.add(user)
        else:
            user.username = username
            user.first_name = first_name
            user.last_name = last_name
            if not getattr(user, "display_name_custom", False):
                user.name_base = telegram_name
                tag_emoji = None
                if user.active_tag_key:
                    from sqlalchemy import select
                    from app.db.models import Achievement
                    achievement = await self.session.scalar(select(Achievement).where(Achievement.key == user.active_tag_key))
                    tag_emoji = achievement.tag_emoji if achievement else None
                user.display_name = f"{tag_emoji} {telegram_name}".strip() if tag_emoji else telegram_name
            user.is_active = True
        await self.session.flush()
        return user
