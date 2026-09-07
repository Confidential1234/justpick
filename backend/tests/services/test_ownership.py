"""The ownership guards themselves, not the routes' handling of them.

This is the closest thing the app has to authorization: an anonymous session id is the
only thing separating one browser's decisions from another's. The route tests stub the
service layer, so they would happily pass with the guard deleted — these do not.

Only the repositories are stubbed, so the real comparisons run.
"""

import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from app.services import decision as service
from app.services.errors import AlreadyDecided, RecommendationMismatch, RequestNotFound

OWNER = uuid.UUID("11111111-1111-1111-1111-111111111111")
INTRUDER = uuid.UUID("22222222-2222-2222-2222-222222222222")
REQUEST_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")
RECOMMENDATION_ID = uuid.UUID("44444444-4444-4444-4444-444444444444")
OTHER_REQUEST_ID = uuid.UUID("55555555-5555-5555-5555-555555555555")

DB: Any = object()  # every repository call is stubbed, so it is never touched


def request_row(session_id: uuid.UUID = OWNER) -> SimpleNamespace:
    return SimpleNamespace(
        id=REQUEST_ID, session_id=session_id, provider_ids=[8, 9], region="US"
    )


def recommendation_row(request_id: uuid.UUID = REQUEST_ID) -> SimpleNamespace:
    return SimpleNamespace(
        id=RECOMMENDATION_ID, request_id=request_id, movie_id=27205, attempt=2
    )


@pytest.fixture
def repo(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Stub the data layer; record what the service tried to write."""
    calls: dict[str, Any] = {"feedback": []}

    def returns(name: str, value: Any) -> None:
        async def fake(*args: Any, **kwargs: Any) -> Any:
            return value() if callable(value) else value

        monkeypatch.setattr(f"app.repositories.decisions.{name}", fake)

    async def record_feedback(*args: Any, **kwargs: Any) -> Any:
        calls["feedback"].append(kwargs)
        return SimpleNamespace(id=uuid.uuid4())

    returns("get_request", request_row())
    returns("get_recommendation", recommendation_row())
    returns("existing_feedback", None)
    returns("latest_recommendation", recommendation_row())
    monkeypatch.setattr("app.repositories.decisions.record_feedback", record_feedback)

    async def movie_view(*args: Any, **kwargs: Any) -> Any:
        return SimpleNamespace(title="Inception")

    monkeypatch.setattr("app.services.catalog.movie_view", movie_view)

    calls["returns"] = returns
    return calls


class TestReadingSomeoneElsesDecision:
    async def test_a_different_session_is_refused(self, repo: dict[str, Any]) -> None:
        with pytest.raises(RequestNotFound):
            await service.get_state(DB, request_id=REQUEST_ID, session_id=INTRUDER)

    async def test_the_owner_is_allowed(self, repo: dict[str, Any]) -> None:
        result = await service.get_state(DB, request_id=REQUEST_ID, session_id=OWNER)
        assert result.request_id == REQUEST_ID

    async def test_a_missing_request_looks_identical_to_someone_elses(
        self, repo: dict[str, Any]
    ) -> None:
        """Distinguishing them would confirm that an id exists to a stranger."""
        repo["returns"]("get_request", None)
        with pytest.raises(RequestNotFound):
            await service.get_state(DB, request_id=REQUEST_ID, session_id=OWNER)


class TestAcceptingSomeoneElsesRecommendation:
    async def test_a_different_session_is_refused(self, repo: dict[str, Any]) -> None:
        with pytest.raises(RequestNotFound):
            await service.accept_recommendation(
                DB,
                request_id=REQUEST_ID,
                session_id=INTRUDER,
                recommendation_id=RECOMMENDATION_ID,
            )

    async def test_nothing_is_written_when_the_session_is_wrong(
        self, repo: dict[str, Any]
    ) -> None:
        with pytest.raises(RequestNotFound):
            await service.accept_recommendation(
                DB,
                request_id=REQUEST_ID,
                session_id=INTRUDER,
                recommendation_id=RECOMMENDATION_ID,
            )
        assert repo["feedback"] == [], "a refused request must not record a verdict"

    async def test_the_owner_is_allowed(self, repo: dict[str, Any]) -> None:
        await service.accept_recommendation(
            DB,
            request_id=REQUEST_ID,
            session_id=OWNER,
            recommendation_id=RECOMMENDATION_ID,
        )
        assert repo["feedback"][0]["action"].value == "accepted"
        assert repo["feedback"][0]["session_id"] == OWNER


class TestRecommendationBelongsToTheRequest:
    async def test_a_recommendation_from_another_request_is_refused(
        self, repo: dict[str, Any]
    ) -> None:
        repo["returns"]("get_recommendation", recommendation_row(OTHER_REQUEST_ID))
        with pytest.raises(RecommendationMismatch):
            await service.accept_recommendation(
                DB,
                request_id=REQUEST_ID,
                session_id=OWNER,
                recommendation_id=RECOMMENDATION_ID,
            )

    async def test_a_recommendation_that_does_not_exist_is_refused(
        self, repo: dict[str, Any]
    ) -> None:
        repo["returns"]("get_recommendation", None)
        with pytest.raises(RecommendationMismatch):
            await service.accept_recommendation(
                DB,
                request_id=REQUEST_ID,
                session_id=OWNER,
                recommendation_id=RECOMMENDATION_ID,
            )


class TestDoubleVerdict:
    async def test_a_second_verdict_is_refused(self, repo: dict[str, Any]) -> None:
        repo["returns"]("existing_feedback", SimpleNamespace(id=uuid.uuid4()))
        with pytest.raises(AlreadyDecided):
            await service.accept_recommendation(
                DB,
                request_id=REQUEST_ID,
                session_id=OWNER,
                recommendation_id=RECOMMENDATION_ID,
            )

    async def test_the_first_verdict_is_not_overwritten(
        self, repo: dict[str, Any]
    ) -> None:
        repo["returns"]("existing_feedback", SimpleNamespace(id=uuid.uuid4()))
        with pytest.raises(AlreadyDecided):
            await service.accept_recommendation(
                DB,
                request_id=REQUEST_ID,
                session_id=OWNER,
                recommendation_id=RECOMMENDATION_ID,
            )
        assert repo["feedback"] == []


class TestRejectGuards:
    async def test_a_different_session_cannot_reject(self, repo: dict[str, Any]) -> None:
        with pytest.raises(RequestNotFound):
            await service.reject_and_next(
                DB,
                None,  # type: ignore[arg-type]  - refused before the client is used
                request_id=REQUEST_ID,
                session_id=INTRUDER,
                recommendation_id=RECOMMENDATION_ID,
                reason="already_seen",
            )
        assert repo["feedback"] == []
