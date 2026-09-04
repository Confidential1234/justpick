"""The decision loop: ask, reject, accept."""

import uuid

from fastapi import APIRouter, Response, status

from app.api import presenters
from app.api.deps import DbSession, SessionId, Tmdb
from app.api.errors import NoCandidates
from app.api.schemas import (
    AcceptedOut,
    AcceptIn,
    DecisionCreate,
    DecisionOut,
    ErrorOut,
    MovieOut,
    RejectIn,
)
from app.engine import DecisionRequest
from app.services import decision as service
from app.services.decision import DecisionOutcome

router = APIRouter(prefix="/decisions", tags=["decisions"])


def _to_response(
    outcome: DecisionOutcome, response: Response, session_id: uuid.UUID
) -> DecisionOut:
    """Turn a successful outcome into the wire shape, or raise the 409."""
    response.headers["X-Session-Id"] = str(session_id)

    if not outcome.found or outcome.movie is None or outcome.recommendation_id is None:
        raise NoCandidates(presenters.relaxation_hints(outcome.relaxation))

    return DecisionOut(
        request_id=outcome.request_id,
        recommendation_id=outcome.recommendation_id,
        attempt=outcome.attempt,
        movie=presenters.movie_out(outcome.movie),
        why=presenters.why(
            outcome.movie, outcome.decision.highlights, outcome.requested_genre_ids
        ),
        highlights=presenters.highlights_out(outcome.decision.highlights),
        candidates_remaining=outcome.decision.candidate_count,
    )


@router.post(
    "",
    response_model=DecisionOut,
    status_code=status.HTTP_201_CREATED,
    responses={409: {"model": ErrorOut, "description": "Nothing matches the constraints"}},
)
async def create_decision(
    body: DecisionCreate,
    db: DbSession,
    client: Tmdb,
    session: SessionId,
    response: Response,
) -> DecisionOut:
    outcome = await service.start(
        db,
        client,
        session_id=session,
        request=DecisionRequest(
            provider_ids=frozenset(body.provider_ids),
            genre_ids=frozenset(body.genre_ids),
            max_runtime=body.max_runtime,
            min_rating=body.min_rating,
        ),
    )
    await db.commit()
    return _to_response(outcome, response, session)


@router.post(
    "/{request_id}/reject",
    response_model=DecisionOut,
    responses={409: {"model": ErrorOut, "description": "Nothing left, or already decided"}},
)
async def reject_decision(
    request_id: uuid.UUID,
    body: RejectIn,
    db: DbSession,
    client: Tmdb,
    session: SessionId,
    response: Response,
) -> DecisionOut:
    outcome = await service.reject_and_next(
        db,
        client,
        request_id=request_id,
        session_id=session,
        recommendation_id=body.recommendation_id,
        reason=body.reason,
        note=body.note,
    )
    await db.commit()
    return _to_response(outcome, response, session)


@router.post("/{request_id}/accept", response_model=AcceptedOut)
async def accept_decision(
    request_id: uuid.UUID,
    body: AcceptIn,
    db: DbSession,
    session: SessionId,
    response: Response,
) -> AcceptedOut:
    view = await service.accept_recommendation(
        db,
        request_id=request_id,
        session_id=session,
        recommendation_id=body.recommendation_id,
    )
    await db.commit()
    response.headers["X-Session-Id"] = str(session)
    return AcceptedOut(movie=presenters.movie_out(view))


@router.get("/{request_id}")
async def read_decision(
    request_id: uuid.UUID, db: DbSession, session: SessionId
) -> dict[str, object]:
    """Current standing of a request, for a refresh or a deep link."""
    state = await service.get_state(db, request_id=request_id, session_id=session)
    movie: MovieOut | None = presenters.movie_out(state.movie) if state.movie else None
    return {
        "request_id": str(state.request_id),
        "attempt": state.attempt,
        "status": state.status,
        "recommendation_id": str(state.recommendation_id) if state.recommendation_id else None,
        "movie": movie.model_dump() if movie else None,
    }
