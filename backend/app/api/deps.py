"""Request-scoped dependencies."""

import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.services.clients import TMDbClient, get_tmdb_client


async def db_session() -> AsyncIterator[AsyncSession]:
    async for session in get_session():
        yield session


def session_id(
    x_session_id: Annotated[str | None, Header(alias="X-Session-Id")] = None,
) -> uuid.UUID:
    """Identify the browser, minting an id when it has not got one yet.

    A malformed or absent header is not an error: the worst case is that someone's
    rejection history starts over, which is better than refusing to recommend a film.
    Responses echo the id so a client can adopt whatever the server used.
    """
    if x_session_id:
        try:
            return uuid.UUID(x_session_id)
        except ValueError:
            pass
    return uuid.uuid4()


def tmdb() -> TMDbClient:
    return get_tmdb_client()


DbSession = Annotated[AsyncSession, Depends(db_session)]
SessionId = Annotated[uuid.UUID, Depends(session_id)]
Tmdb = Annotated[TMDbClient, Depends(tmdb)]
