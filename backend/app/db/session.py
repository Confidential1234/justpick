"""Async engine and session management.

The engine is created lazily so the app can boot, and /health can answer, with no
database configured at all.
"""

from collections.abc import AsyncIterator
from typing import Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None

DatabaseStatus = Literal["ok", "unavailable", "not_configured"]


def get_engine() -> AsyncEngine | None:
    global _engine, _sessionmaker
    settings = get_settings()
    if settings.database_url is None:
        return None
    if _engine is None:
        _engine = create_async_engine(settings.database_url, pool_pre_ping=True)
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a session bound to one request."""
    if get_engine() is None or _sessionmaker is None:
        raise RuntimeError("DATABASE_URL is not configured")
    async with _sessionmaker() as session:
        yield session


async def ping_database() -> DatabaseStatus:
    engine = get_engine()
    if engine is None:
        return "not_configured"
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001 - health check reports, it does not raise
        return "unavailable"
    return "ok"


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None
