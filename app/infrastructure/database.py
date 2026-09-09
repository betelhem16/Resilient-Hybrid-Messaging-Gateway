from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings

_settings = get_settings()

engine: AsyncEngine = create_async_engine(
    _settings.database_url,
    pool_size=_settings.db_pool_size,
    pool_pre_ping=True,  # Detects connections killed by a Postgres restart.
    echo=False,
)

# expire_on_commit=False keeps ORM attributes readable after commit, which
# matters in async code where a lazy refresh would trigger unexpected I/O.
SessionFactory = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a session scoped to one request."""
    async with SessionFactory() as session:
        yield session
