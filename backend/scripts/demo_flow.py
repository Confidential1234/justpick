"""Run a full decision loop against the real database and the real TMDb API.

Start a request, reject the first suggestion, accept the second, then show what landed
in the tables.

    python -m scripts.demo_flow
"""

import asyncio
import sys
import uuid

from sqlalchemy import func, select

from app.config import get_settings
from app.db import models
from app.db.session import dispose_engine, get_engine, get_sessionmaker
from app.engine import DecisionRequest
from app.services import decision as decision_service
from app.tmdb.client import NETFLIX, PRIME_VIDEO, TMDbClient

REQUEST = DecisionRequest(
    provider_ids=frozenset({NETFLIX, PRIME_VIDEO}),
    genre_ids=frozenset({28, 878}),  # Action or Sci-Fi
    max_runtime=120,
    min_rating=None,
)

COUNTED = (
    models.Movie,
    models.MovieGenre,
    models.MovieProvider,
    models.Session,
    models.DecisionRequestRow,
    models.Recommendation,
    models.Feedback,
)


def show(label: str, outcome: decision_service.DecisionOutcome) -> None:
    if not outcome.found:
        print(f"{label}: nothing fits")
        for constraint, count in outcome.relaxation.items():
            print(f"    relaxing {constraint.value:<8} -> {count:,} movies")
        return
    movie = outcome.decision.movie
    details = outcome.details
    assert movie is not None and details is not None
    runtime = f"{details.runtime_minutes} min" if details.runtime_minutes else "runtime ?"
    services = ", ".join(p.name for p in outcome.available_on) or "unknown"
    print(
        f"{label}: {movie.title} ({runtime}, {movie.vote_average:.1f})"
        f"  score {outcome.decision.breakdown.total:.3f}"  # type: ignore[union-attr]
        f"  top {outcome.decision.band_size}/{outcome.decision.candidate_count}"
    )
    print(f"    on {services}")


async def run() -> int:
    settings = get_settings()
    if not settings.tmdb_api_token or get_engine() is None:
        sys.exit("TMDB_API_TOKEN and DATABASE_URL must both be set")

    session_id = uuid.uuid4()
    print(f"session {session_id}\n")

    sessionmaker = get_sessionmaker()
    async with (
        TMDbClient(settings.tmdb_api_token, settings.tmdb_base_url) as client,
        sessionmaker() as db,
    ):
        first = await decision_service.start(db, client, session_id=session_id, request=REQUEST)
        await db.commit()
        show("attempt 1", first)

        assert first.recommendation_id and first.decision.movie
        await decision_service.reject(
            db,
            recommendation_id=first.recommendation_id,
            session_id=session_id,
            movie_id=first.decision.movie.tmdb_id,
            reason="already_seen",
        )
        await db.commit()
        print("    -> rejected (already_seen)\n")

        row = await db.get(models.DecisionRequestRow, first.request_id)
        assert row is not None
        second = await decision_service.next_pick(db, client, row=row, session_id=session_id)
        await db.commit()
        show("attempt 2", second)

        assert second.recommendation_id and second.decision.movie
        await decision_service.accept(
            db,
            recommendation_id=second.recommendation_id,
            session_id=session_id,
            movie_id=second.decision.movie.tmdb_id,
        )
        await db.commit()
        print("    -> accepted\n")

    async with sessionmaker() as db:
        print("table totals")
        for model in COUNTED:
            total = await db.scalar(select(func.count()).select_from(model))
            print(f"  {model.__tablename__:<20}{total:>6}")

        cached = await db.scalar(
            select(func.count())
            .select_from(models.Movie)
            .where(models.Movie.runtime_minutes.is_not(None))
        )
        print(f"\nmovies with a cached runtime: {cached}")

        stored = await db.scalar(
            select(models.Recommendation.score_breakdown)
            .order_by(models.Recommendation.created_at.desc())
            .limit(1)
        )
        print(f"last score_breakdown: {stored}")
    return 0


async def _with_cleanup() -> int:
    try:
        return await run()
    finally:
        await dispose_engine()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_with_cleanup()))
