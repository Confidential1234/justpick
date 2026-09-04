"""Async engine and session management.

The engine is created lazily so the app can boot, and /health can answer, with no
database configured at all.
"""

from collections.abc import AsyncIterator
from typing import Literal

from sqlalchemy import text
from sqlalchemy.engine import make_url
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


def _connect_args(url: str) -> dict[str, object]:
    """Hosted Postgres requires TLS; a local socket does not offer it.

    asyncpg takes `ssl` rather than libpq's `sslmode`, and it is not a URL parameter,
    which is why the settings validator strips sslmode and the decision lands here.
    """
    host = make_url(url).host or ""
    if host in {"localhost", "127.0.0.1", "::1", "db"}:
        return {}
    return {"ssl": "require"}


def get_engine() -> AsyncEngine | None:
    global _engine, _sessionmaker
    settings = get_settings()
    if settings.database_url is None:
        return None
    if _engine is None:
        _engine = create_async_engine(
            settings.database_url,
            pool_pre_ping=True,  # hosted Postgres drops idle connections
            connect_args=_connect_args(settings.database_url),
        )
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """For callers outside a request, e.g. scripts. Raises if no database is configured."""
    if get_engine() is None or _sessionmaker is None:
        raise RuntimeError("DATABASE_URL is not configured")
    return _sessionmaker


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
