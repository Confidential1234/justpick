"""Route-level tests: the web layer only, with the service layer stubbed out.

The point is to test what the routes themselves are responsible for — status codes, the
error contract, validation bounds, session handling, and how presenters render a movie —
without a database or a network. Whether TMDb returns real films and whether Postgres
persists rows is checked by scripts/demo_flow.py against real infrastructure; mocking
those here would only test the mocks.
"""

import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any

import httpx
import pytest

from app.api import deps
from app.engine.models import (
    CandidateMovie,
    Constraint,
    Decision,
    DecisionReason,
    Highlight,
    ScoreBreakdown,
)
from app.main import app
from app.services.decision import DecisionOutcome, DecisionState
from app.services.views import GenreOption, MovieView, ProviderOption

ACTION, SCIFI, THRILLER = 28, 878, 53
NETFLIX, PRIME = 8, 9

SESSION = uuid.UUID("11111111-1111-1111-1111-111111111111")
OTHER_SESSION = uuid.UUID("22222222-2222-2222-2222-222222222222")
REQUEST_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")
RECOMMENDATION_ID = uuid.UUID("44444444-4444-4444-4444-444444444444")


class StubSession:
    """Stands in for AsyncSession. Routes only ever commit; the services are stubbed."""

    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:  # pragma: no cover - safety net
        pass


@pytest.fixture
def stub_db() -> StubSession:
    return StubSession()


@pytest.fixture(autouse=True)
def overrides(stub_db: StubSession) -> Iterator[None]:
    async def fake_db() -> AsyncIterator[StubSession]:
        yield stub_db

    app.dependency_overrides[deps.db_session] = fake_db
    app.dependency_overrides[deps.tmdb] = lambda: object()
    yield
    app.dependency_overrides.clear()


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


HEADERS = {"X-Session-Id": str(SESSION)}


# ------------------------------------------------------------------- canned values


def movie_view(**overrides: Any) -> MovieView:
    defaults: dict[str, Any] = {
        "tmdb_id": 27205,
        "title": "Inception",
        "overview": "A thief who steals corporate secrets.",
        "release_year": 2010,
        "runtime_minutes": 148,
        "vote_average": 8.4,
        "vote_count": 36012,
        "poster_url": "https://image.tmdb.org/t/p/w500/poster.jpg",
        "genres": (
            GenreOption(id=ACTION, name="Action"),
            GenreOption(id=THRILLER, name="Thriller"),
            GenreOption(id=SCIFI, name="Science Fiction"),
        ),
        "providers": (ProviderOption(id=NETFLIX, name="Netflix", logo_url=None),),
        "tmdb_url": "https://www.themoviedb.org/movie/27205",
    }
    return MovieView(**(defaults | overrides))


def decision(**overrides: Any) -> Decision:
    breakdown = ScoreBreakdown(genre_match=1.0, rating=0.85, runtime_fit=0.9, total=0.9175)
    defaults: dict[str, Any] = {
        "reason": DecisionReason.OK,
        "movie": CandidateMovie(
            tmdb_id=27205,
            title="Inception",
            genre_ids=frozenset({ACTION, SCIFI}),
            provider_ids=frozenset({NETFLIX}),
            vote_average=8.4,
            vote_count=36012,
        ),
        "breakdown": breakdown,
        "highlights": (
            Highlight(component="genre_match", contribution=0.4),
            Highlight(component="rating", contribution=0.255),
        ),
        "candidate_count": 41,
        "band_size": 5,
    }
    return Decision(**(defaults | overrides))


def outcome(**overrides: Any) -> DecisionOutcome:
    defaults: dict[str, Any] = {
        "request_id": REQUEST_ID,
        "attempt": 1,
        "decision": decision(),
        "recommendation_id": RECOMMENDATION_ID,
        "movie": movie_view(),
        "requested_genre_ids": frozenset({ACTION, SCIFI}),
        "relaxation": {},
    }
    return DecisionOutcome(**(defaults | overrides))


def empty_outcome(relaxation: dict[Constraint, int] | None = None) -> DecisionOutcome:
    return DecisionOutcome(
        request_id=REQUEST_ID,
        attempt=1,
        decision=decision(
            reason=DecisionReason.NO_CANDIDATES,
            movie=None,
            breakdown=None,
            highlights=(),
            candidate_count=0,
            band_size=0,
        ),
        recommendation_id=None,
        movie=None,
        relaxation=relaxation
        or {Constraint.RATING: 113, Constraint.GENRE: 2, Constraint.RUNTIME: 0},
    )


def state(**overrides: Any) -> DecisionState:
    defaults: dict[str, Any] = {
        "request_id": REQUEST_ID,
        "attempt": 2,
        "status": "pending",
        "recommendation_id": RECOMMENDATION_ID,
        "movie": movie_view(),
    }
    return DecisionState(**(defaults | overrides))


VALID_BODY = {
    "provider_ids": [NETFLIX, PRIME],
    "genre_ids": [ACTION, SCIFI],
    "max_runtime": 120,
    "min_rating": None,
}
