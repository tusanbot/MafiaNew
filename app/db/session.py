from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from app.config import get_settings

_settings = get_settings()

# The bot runs several independent background timers (turns, voting, challenges)
# and Telegram callbacks concurrently. The default SQLAlchemy asyncpg pool is
# intentionally small and can make unrelated button presses wait for a free
# connection. Keep a bounded, reusable pool for PostgreSQL.
_engine_kwargs = {
    "pool_pre_ping": True,
    "pool_recycle": 1800,
}
if _settings.database_url.startswith(("postgresql://", "postgresql+asyncpg://")):
    _engine_kwargs.update({
        "pool_size": 20,
        "max_overflow": 20,
        "pool_timeout": 5,
    })

engine = create_async_engine(_settings.database_url, **_engine_kwargs)
session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)