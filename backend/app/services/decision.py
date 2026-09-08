"""Orchestration: constraints in, one persisted recommendation out.

The only module that knows about all four of TMDb, the cache, the engine and the tables.
Everything it coordinates stays independently testable because none of them know about
each other.
"""

import uuid
from dataclasses import dataclass, field, replace
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DecisionRequestRow, FeedbackAction, Recommendation
from app.engine import CandidateMovie, Decision, DecisionRequest, decide
from app.engine.models import Constraint, DecisionReason
from app.repositories import decisions as decisions_repo
from app.repositories import sessions as sessions_repo
from app.services import catalog
from app.services.errors import AlreadyDecided, RecommendationMismatch, RequestNotFound
from app.services.views import MovieView, ProviderOption, from_details, image_url
from app.tmdb.client import TMDbClient
from app.tmdb.models import MovieDetails


@dataclass(slots=True)
class DecisionOutcome:
    request_id: uuid.UUID
    attempt: int
    decision: Decision
    recommendation_id: uuid.UUID | None = None
    movie: MovieView | None = None
    # Carried through so the explanation can name the genres the user asked for, rather
    # than whichever genres the film happens to be tagged with.
    requested_genre_ids: frozenset[int] = frozenset()
    relaxation: dict[Constraint, int] = field(default_factory=dict)

    @property
    def found(self) -> bool:
        return self.decision.found


def _to_engine_request(row: DecisionRequestRow) -> DecisionRequest:
    return DecisionRequest(
        provider_ids=frozenset(row.provider_ids),
        genre_ids=frozenset(row.genre_ids),
        max_runtime=row.max_runtime,
        min_rating=float(row.min_rating) if row.min_rating is not None else None,
        min_year=row.min_year,
    )


def _breakdown_dict(decision: Decision) -> dict[str, float]:
    assert decision.breakdown is not None
    return {
        "genre_match": float(decision.breakdown.genre_match),
        "rating": float(decision.breakdown.rating),
        "runtime_fit": float(decision.breakdown.runtime_fit),
        "total": float(decision.breakdown.total),
    }


async def start(
    db: AsyncSession,
    client: TMDbClient,
    *,
    session_id: uuid.UUID,
    request: DecisionRequest,
    user_agent: str | None = None,
    region: str = "US",
) -> DecisionOutcome:
    """Begin a new decision: record the constraints, then answer them."""
    await sessions_repo.touch(db, session_id, user_agent)
    row = await decisions_repo.create_request(
        db,
        session_id=session_id,
        provider_ids=sorted(request.provider_ids),
        genre_ids=sorted(request.genre_ids),
        max_runtime=request.max_runtime,
        min_rating=request.min_rating,
        min_year=request.min_year,
        region=region,
    )
    return await _answer(db, client, row=row, session_id=session_id, region=region)


async def next_pick(
    db: AsyncSession,
    client: TMDbClient,
    *,
    row: DecisionRequestRow,
    session_id: uuid.UUID,
    region: str = "US",
) -> DecisionOutcome:
    """Answer an existing request again, after a rejection."""
    return await _answer(db, client, row=row, session_id=session_id, region=region)


# TMDb's with_runtime.lte filter leaks: measured against the live API, 6 of 40 results
# for a 120-minute request were longer than that, up to a 170-minute Scarface. Discover
# does not return runtimes, so nothing catches it until the details call.
#
# So verify the winner and re-decide if it does not actually fit. The cost is usually
# nothing — the details call happens anyway — and hydrate() caches the real runtime, so
# the same film is eliminated by the engine's own constraint on every later request. The
# leak rate decays as the cache warms rather than persisting.
MAX_RUNTIME_RETRIES = 5


async def _decide_and_verify(
    db: AsyncSession,
    client: TMDbClient,
    *,
    candidates: list[CandidateMovie],
    request: DecisionRequest,
    excluded: frozenset[int],
    seed_prefix: str,
    region: str,
) -> tuple[Decision, MovieDetails | None, list[CandidateMovie]]:
    today = date.today()

    for _ in range(MAX_RUNTIME_RETRIES):
        decision = decide(candidates, request, excluded, seed=seed_prefix, today=today)
        if decision.reason is DecisionReason.NO_CANDIDATES:
            return decision, None, candidates

        assert decision.movie is not None
        details = await catalog.hydrate(client, db, decision.movie.tmdb_id, region=region)

        runtime = details.runtime_minutes
        if runtime is None or runtime <= request.max_runtime:
            return decision, details, candidates

        # Correct the candidate in place and let the engine's RUNTIME constraint drop it,
        # rather than special-casing the exclusion here.
        candidates = [
            replace(c, runtime_minutes=runtime) if c.tmdb_id == decision.movie.tmdb_id else c
            for c in candidates
        ]

    # Every attempt overran. Better to report nothing than to break the one promise the
    # app makes about fitting the time available.
    return (
        Decision(
            reason=DecisionReason.NO_CANDIDATES,
            movie=None,
            breakdown=None,
            highlights=(),
            candidate_count=0,
            band_size=0,
        ),
        None,
        candidates,
    )


async def _answer(
    db: AsyncSession,
    client: TMDbClient,
    *,
    row: DecisionRequestRow,
    session_id: uuid.UUID,
    region: str,
) -> DecisionOutcome:
    request = _to_engine_request(row)
    attempt = await decisions_repo.next_attempt(db, row.id)

    # Two exclusion sources with different lifetimes: the session's recent verdicts
    # expire after a cooldown, whereas anything already served in this request must never
    # come back regardless.
    excluded = await sessions_repo.excluded_movie_ids(db, session_id)
    excluded |= await decisions_repo.served_movie_ids(db, row.id)

    candidates = await catalog.fetch_candidates(client, db, request, region=region)
    decision, details, candidates = await _decide_and_verify(
        db,
        client,
        candidates=candidates,
        request=request,
        excluded=frozenset(excluded),
        seed_prefix=f"{session_id}:{attempt}",
        region=region,
    )

    if decision.reason is DecisionReason.NO_CANDIDATES or details is None:
        return DecisionOutcome(
            request_id=row.id,
            attempt=attempt,
            decision=decision,
            requested_genre_ids=request.genre_ids,
            relaxation=await catalog.relaxation_counts(client, request, region=region),
        )

    assert decision.movie is not None
    recommendation = await decisions_repo.record_recommendation(
        db,
        request_id=row.id,
        movie_id=decision.movie.tmdb_id,
        attempt=attempt,
        score=float(decision.breakdown.total),  # type: ignore[union-attr]
        score_breakdown=_breakdown_dict(decision),
        candidate_count=decision.candidate_count,
        band_size=decision.band_size,
    )
    # Only the services the user actually subscribes to. TMDb lists every flatrate
    # carrier, so a film can come back "on Paramount+, Philo, fuboTV..." — naming a
    # service someone does not have is worse than naming none.
    available_on = tuple(
        ProviderOption(id=p.id, name=p.name, logo_url=image_url(p.logo_path, size="original"))
        for p in details.flatrate_providers
        if p.id in request.provider_ids
    )
    return DecisionOutcome(
        request_id=row.id,
        attempt=attempt,
        decision=decision,
        recommendation_id=recommendation.id,
        movie=from_details(details, available_on),
        requested_genre_ids=request.genre_ids,
    )


async def accept(
    db: AsyncSession, *, recommendation_id: uuid.UUID, session_id: uuid.UUID, movie_id: int
) -> None:
    await decisions_repo.record_feedback(
        db,
        recommendation_id=recommendation_id,
        session_id=session_id,
        movie_id=movie_id,
        action=FeedbackAction.ACCEPTED,
    )


async def reject(
    db: AsyncSession,
    *,
    recommendation_id: uuid.UUID,
    session_id: uuid.UUID,
    movie_id: int,
    reason: str,
    note: str | None = None,
) -> None:
    await decisions_repo.record_feedback(
        db,
        recommendation_id=recommendation_id,
        session_id=session_id,
        movie_id=movie_id,
        action=FeedbackAction.REJECTED,
        reason=reason,
        note=note,
    )


# ----------------------------------------------------------------- request-level flows
#
# The API calls these rather than the pieces above, so routes never hold an ORM row and
# never have to know the ordering rules (verdict recorded before the next pick).


async def _owned_recommendation(
    db: AsyncSession, *, request_id: uuid.UUID, recommendation_id: uuid.UUID
) -> Recommendation:
    recommendation = await decisions_repo.get_recommendation(db, recommendation_id)
    if recommendation is None or recommendation.request_id != request_id:
        raise RecommendationMismatch(str(recommendation_id))
    if await decisions_repo.existing_feedback(db, recommendation_id) is not None:
        raise AlreadyDecided(str(recommendation_id))
    return recommendation


async def _owned_request(
    db: AsyncSession, *, request_id: uuid.UUID, session_id: uuid.UUID
) -> DecisionRequestRow:
    row = await decisions_repo.get_request(db, request_id)
    if row is None or row.session_id != session_id:
        # Same response either way: a wrong session must not reveal that the id exists.
        raise RequestNotFound(str(request_id))
    return row


async def reject_and_next(
    db: AsyncSession,
    client: TMDbClient,
    *,
    request_id: uuid.UUID,
    session_id: uuid.UUID,
    recommendation_id: uuid.UUID,
    reason: str,
    note: str | None = None,
) -> DecisionOutcome:
    row = await _owned_request(db, request_id=request_id, session_id=session_id)
    recommendation = await _owned_recommendation(
        db, request_id=request_id, recommendation_id=recommendation_id
    )
    await reject(
        db,
        recommendation_id=recommendation_id,
        session_id=session_id,
        movie_id=recommendation.movie_id,
        reason=reason,
        note=note,
    )
    return await next_pick(db, client, row=row, session_id=session_id, region=row.region)


async def accept_recommendation(
    db: AsyncSession,
    *,
    request_id: uuid.UUID,
    session_id: uuid.UUID,
    recommendation_id: uuid.UUID,
) -> MovieView:
    row = await _owned_request(db, request_id=request_id, session_id=session_id)
    recommendation = await _owned_recommendation(
        db, request_id=request_id, recommendation_id=recommendation_id
    )
    await accept(
        db,
        recommendation_id=recommendation_id,
        session_id=session_id,
        movie_id=recommendation.movie_id,
    )
    view = await catalog.movie_view(
        db, recommendation.movie_id, frozenset(row.provider_ids), region=row.region
    )
    if view is None:
        raise RequestNotFound(str(request_id))
    return view


@dataclass(slots=True)
class DecisionState:
    request_id: uuid.UUID
    attempt: int
    status: str
    recommendation_id: uuid.UUID | None = None
    movie: MovieView | None = None


async def get_state(
    db: AsyncSession, *, request_id: uuid.UUID, session_id: uuid.UUID
) -> DecisionState:
    """The current standing of a request, for a page refresh or a deep link."""
    row = await _owned_request(db, request_id=request_id, session_id=session_id)
    recommendation = await decisions_repo.latest_recommendation(db, request_id)
    if recommendation is None:
        return DecisionState(request_id=request_id, attempt=0, status="empty")

    feedback = await decisions_repo.existing_feedback(db, recommendation.id)
    status = feedback.action.value if feedback is not None else "pending"
    view = await catalog.movie_view(
        db, recommendation.movie_id, frozenset(row.provider_ids), region=row.region
    )
    return DecisionState(
        request_id=request_id,
        attempt=recommendation.attempt,
        status=status,
        recommendation_id=recommendation.id,
        movie=view,
    )
