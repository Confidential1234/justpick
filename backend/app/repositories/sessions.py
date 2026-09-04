"""Anonymous sessions, and the exclusion list derived from their feedback."""

import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Feedback, Session

# How long a movie stays out of rotation after being accepted or rejected. Per browser,
# since sessions are anonymous - clearing localStorage resets someone's history.
EXCLUSION_COOLDOWN = timedelta(days=30)


async def touch(
    db: AsyncSession, session_id: uuid.UUID, user_agent: str | None = None
) -> uuid.UUID:
    """Create the session row if this is a new browser, otherwise bump last_seen_at.

    The client mints its own UUID, so the first request from a browser carries an id the
    server has never seen. That is not an error condition, it is the normal path.
    """
    stmt = insert(Session).values(id=session_id, user_agent=user_agent)
    await db.execute(
        stmt.on_conflict_do_update(
            index_elements=[Session.id], set_={"last_seen_at": func.now()}
        )
    )
    return session_id


async def excluded_movie_ids(
    db: AsyncSession, session_id: uuid.UUID, cooldown: timedelta = EXCLUSION_COOLDOWN
) -> set[int]:
    """Everything this session has already ruled on.

    Accepted films are excluded alongside rejected ones — you just watched it, so it is
    the last thing you want offered again tonight.
    """
    cutoff = datetime.now(tz=None).astimezone() - cooldown
    result = await db.execute(
        select(Feedback.movie_id).where(
            Feedback.session_id == session_id, Feedback.created_at >= cutoff
        )
    )
    return set(result.scalars())
