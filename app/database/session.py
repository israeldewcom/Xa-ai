import asyncio
import logging
from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine,
)

from app.config import get_settings
from app.database.models import Base

logger = logging.getLogger("xa.db")
_s = get_settings()

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _make_engine() -> AsyncEngine:
    kwargs: dict = {"echo": _s.db_echo, "future": True}
    if "postgresql" in _s.database_url:
        kwargs.update(
            pool_size=_s.db_pool_size,
            max_overflow=_s.db_max_overflow,
            pool_recycle=_s.db_pool_recycle_seconds,
            pool_pre_ping=True,
        )
    return create_async_engine(_s.database_url, **kwargs)


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = _make_engine()
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(), expire_on_commit=False, class_=AsyncSession,
        )
    return _session_factory


class _SessionProxy:
    """Lazy AsyncSessionLocal so module import doesn't create the engine."""
    def __call__(self) -> AsyncSession:
        return get_session_factory()()


AsyncSessionLocal = _SessionProxy()


async def get_db() -> AsyncIterator[AsyncSession]:
    async with get_session_factory()() as session:
        yield session


async def init_db() -> None:
    engine = get_engine()
    for attempt in range(_s.db_connect_retries):
        try:
            async with engine.begin() as conn:
                if _s.environment == "production":
                    # Alembic owns the schema in production.
                    await conn.execute(text("SELECT 1"))
                else:
                    await conn.run_sync(Base.metadata.create_all)
            logger.info("db_ready")
            return
        except Exception as exc:
            wait = 2 ** attempt
            logger.warning("db_connect_failed", extra={
                "attempt": attempt + 1, "error": str(exc), "wait": wait,
            })
            if attempt == _s.db_connect_retries - 1:
                raise
            await asyncio.sleep(wait)
