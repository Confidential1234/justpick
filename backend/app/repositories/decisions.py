"""Persistence for requests, the recommendations they produced, and the user's verdict.

Takes primitives rather than engine objects — this layer must not import app.engine.
"""

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DecisionRequestRow, Feedback, FeedbackAction, Recommendation


async def create_request(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    provider_ids: Sequence[int],
    genre_ids: Sequence[int],
    max_runtime: int,
    min_rating: float | None,
    min_year: int | None = None,
    region: str = "US",
) -> DecisionRequestRow:
    row = DecisionRequestRow(
        session_id=session_id,
        provider_ids=sorted(provider_ids),
        genre_ids=sorted(genre_ids),
        max_runtime=max_runtime,
        min_rating=min_rating,
        min_year=min_year,
        region=region,
    )
    db.add(row)
    await db.flush()
    return row


async def get_request(db: AsyncSession, request_id: uuid.UUID) -> DecisionRequestRow | None:
    return await db.get(DecisionRequestRow, request_id)


async def next_attempt(db: AsyncSession, request_id: uuid.UUID) -> int:
    highest = await db.scalar(
        select(func.max(Recommendation.attempt)).where(Recommendation.request_id == request_id)
    )
    return (highest or 0) + 1


async def served_movie_ids(db: AsyncSession, request_id: uuid.UUID) -> set[int]:
    """Films already offered within this request.

    Separate from the session-wide exclusion list: those expire after a cooldown, these
    must never repeat inside a single sitting no matter what.
    """
    result = await db.execute(
        select(Recommendation.movie_id).where(Recommendation.request_id == request_id)
    )
    return set(result.scalars())


async def record_recommendation(
    db: AsyncSession,
    *,
    request_id: uuid.UUID,
    movie_id: int,
    attempt: int,
    score: float,
    score_breakdown: dict[str, Any],
    candidate_count: int,
    band_size: int,
) -> Recommendation:
    row = Recommendation(
        request_id=request_id,
        movie_id=movie_id,
        attempt=attempt,
        score=score,
        score_breakdown=score_breakdown,
        candidate_count=candidate_count,
        band_size=band_size,
    )
    db.add(row)
    await db.flush()
    return row


async def get_recommendation(
    db: AsyncSession, recommendation_id: uuid.UUID
) -> Recommendation | None:
    return await db.get(Recommendation, recommendation_id)


async def latest_recommendation(
    db: AsyncSession, request_id: uuid.UUID
) -> Recommendation | None:
    return await db.scalar(
        select(Recommendation)
        .where(Recommendation.request_id == request_id)
        .order_by(Recommendation.attempt.desc())
        .limit(1)
    )


async def record_feedback(
    db: AsyncSession,
    *,
    recommendation_id: uuid.UUID,
    session_id: uuid.UUID,
    movie_id: int,
    action: FeedbackAction,
    reason: str | None = None,
    note: str | None = None,
) -> Feedback:
    row = Feedback(
        recommendation_id=recommendation_id,
        session_id=session_id,
        movie_id=movie_id,
        action=action,
        reason=reason,
        note=note,
    )
    db.add(row)
    await db.flush()
    return row


async def existing_feedback(
    db: AsyncSession, recommendation_id: uuid.UUID
) -> Feedback | None:
    """A recommendation can only be ruled on once; the unique index enforces it."""
    return await db.scalar(
        select(Feedback).where(Feedback.recommendation_id == recommendation_id)
    )
