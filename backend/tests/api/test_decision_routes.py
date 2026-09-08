"""The decision endpoints: what they return, and what they refuse."""

import uuid
from typing import Any

import httpx
import pytest

from app.engine.models import Constraint
from app.services.errors import (
    AlreadyDecided,
    RecommendationMismatch,
    RequestNotFound,
    UpstreamFailure,
    UpstreamUnavailable,
)

from .conftest import (
    HEADERS,
    RECOMMENDATION_ID,
    REQUEST_ID,
    SESSION,
    VALID_BODY,
    StubSession,
    empty_outcome,
    movie_view,
    outcome,
    state,
)


def stub(monkeypatch: pytest.MonkeyPatch, name: str, result: Any) -> dict[str, Any]:
    """Replace a service function, recording the keyword arguments it was called with."""
    seen: dict[str, Any] = {}

    async def fake(*args: Any, **kwargs: Any) -> Any:
        seen.update(kwargs)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(f"app.services.decision.{name}", fake)
    return seen


class TestCreate:
    async def test_returns_one_movie_with_reasons(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stub(monkeypatch, "start", outcome())
        response = await client.post("/api/v1/decisions", json=VALID_BODY, headers=HEADERS)

        assert response.status_code == 201
        body = response.json()
        assert body["movie"]["title"] == "Inception"
        assert body["attempt"] == 1
        assert body["candidates_remaining"] == 41
        assert body["recommendation_id"] == str(RECOMMENDATION_ID)
        assert body["movie"]["providers"] == [
            {"id": 8, "name": "Netflix", "logo_url": None}
        ]

    async def test_reasons_name_only_the_genres_that_were_asked_for(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The film is also tagged Thriller, which the user did not request."""
        stub(monkeypatch, "start", outcome())
        response = await client.post("/api/v1/decisions", json=VALID_BODY, headers=HEADERS)

        why = response.json()["why"]
        assert why[0] == "Matches Action, Science Fiction"
        assert not any("Thriller" in reason for reason in why)

    async def test_commits_the_transaction(
        self,
        client: httpx.AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
        stub_db: StubSession,
    ) -> None:
        stub(monkeypatch, "start", outcome())
        await client.post("/api/v1/decisions", json=VALID_BODY, headers=HEADERS)
        assert stub_db.commits == 1

    async def test_passes_the_session_from_the_header_through(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen = stub(monkeypatch, "start", outcome())
        await client.post("/api/v1/decisions", json=VALID_BODY, headers=HEADERS)
        assert seen["session_id"] == SESSION

    async def test_deduplicates_and_sorts_ids(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen = stub(monkeypatch, "start", outcome())
        await client.post(
            "/api/v1/decisions",
            json={**VALID_BODY, "provider_ids": [9, 8, 9], "genre_ids": [878, 28, 28]},
            headers=HEADERS,
        )
        assert seen["request"].provider_ids == frozenset({8, 9})
        assert seen["request"].genre_ids == frozenset({28, 878})


class TestSessionHandling:
    async def test_echoes_the_session_id_so_a_client_can_adopt_it(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stub(monkeypatch, "start", outcome())
        response = await client.post("/api/v1/decisions", json=VALID_BODY, headers=HEADERS)
        assert response.headers["X-Session-Id"] == str(SESSION)

    @pytest.mark.parametrize("headers", [{}, {"X-Session-Id": "not-a-uuid"}])
    async def test_a_missing_or_broken_header_still_gets_a_movie(
        self,
        client: httpx.AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
        headers: dict[str, str],
    ) -> None:
        """Refusing to recommend a film is worse than restarting someone's history."""
        seen = stub(monkeypatch, "start", outcome())
        response = await client.post("/api/v1/decisions", json=VALID_BODY, headers=headers)

        assert response.status_code == 201
        minted = uuid.UUID(response.headers["X-Session-Id"])
        assert seen["session_id"] == minted


class TestValidation:
    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("provider_ids", []),
            ("max_runtime", 10),
            ("max_runtime", 999),
            ("min_rating", -1),
            ("min_rating", 11),
            ("min_year", 1600),
        ],
    )
    async def test_rejects_out_of_range_input(
        self, client: httpx.AsyncClient, field: str, value: Any
    ) -> None:
        response = await client.post(
            "/api/v1/decisions", json={**VALID_BODY, field: value}, headers=HEADERS
        )
        assert response.status_code == 422

    async def test_a_release_year_floor_is_passed_through(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen = stub(monkeypatch, "start", outcome())
        response = await client.post(
            "/api/v1/decisions", json={**VALID_BODY, "min_year": 1990}, headers=HEADERS
        )
        assert response.status_code == 201
        assert seen["request"].min_year == 1990

    async def test_the_year_floor_is_optional(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen = stub(monkeypatch, "start", outcome())
        await client.post("/api/v1/decisions", json=VALID_BODY, headers=HEADERS)
        assert seen["request"].min_year is None

    async def test_genres_are_optional(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen = stub(monkeypatch, "start", outcome())
        body = {k: v for k, v in VALID_BODY.items() if k != "genre_ids"}
        response = await client.post("/api/v1/decisions", json=body, headers=HEADERS)

        assert response.status_code == 201
        assert seen["request"].genre_ids == frozenset()


class TestNoCandidates:
    async def test_answers_409_with_what_to_loosen(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stub(monkeypatch, "start", empty_outcome())
        response = await client.post("/api/v1/decisions", json=VALID_BODY, headers=HEADERS)

        assert response.status_code == 409
        body = response.json()
        assert body["error"] == "no_candidates"
        assert [h["field"] for h in body["relaxation_hints"]] == ["min_rating", "genre_ids"]
        assert body["relaxation_hints"][0]["would_yield"] == 113

    async def test_uses_the_same_flat_error_shape_as_everything_else(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """It used to nest under "detail", forcing clients to parse two shapes."""
        stub(monkeypatch, "start", empty_outcome())
        body = (
            await client.post("/api/v1/decisions", json=VALID_BODY, headers=HEADERS)
        ).json()
        assert set(body) == {"error", "message", "relaxation_hints"}
        assert "detail" not in body

    async def test_omits_relaxations_that_would_still_find_nothing(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stub(monkeypatch, "start", empty_outcome({Constraint.RUNTIME: 0}))
        body = (
            await client.post("/api/v1/decisions", json=VALID_BODY, headers=HEADERS)
        ).json()
        assert body["relaxation_hints"] == []


class TestReject:
    async def test_returns_a_different_movie(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stub(
            monkeypatch,
            "reject_and_next",
            outcome(attempt=2, movie=movie_view(tmdb_id=680, title="Pulp Fiction")),
        )
        response = await client.post(
            f"/api/v1/decisions/{REQUEST_ID}/reject",
            json={"recommendation_id": str(RECOMMENDATION_ID), "reason": "already_seen"},
            headers=HEADERS,
        )

        assert response.status_code == 200
        assert response.json()["movie"]["title"] == "Pulp Fiction"
        assert response.json()["attempt"] == 2

    async def test_forwards_the_reason(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen = stub(monkeypatch, "reject_and_next", outcome(attempt=2))
        await client.post(
            f"/api/v1/decisions/{REQUEST_ID}/reject",
            json={
                "recommendation_id": str(RECOMMENDATION_ID),
                "reason": "too_long",
                "note": "past my bedtime",
            },
            headers=HEADERS,
        )
        assert seen["reason"] == "too_long"
        assert seen["note"] == "past my bedtime"

    async def test_running_out_of_movies_is_a_409_not_a_crash(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stub(monkeypatch, "reject_and_next", empty_outcome())
        response = await client.post(
            f"/api/v1/decisions/{REQUEST_ID}/reject",
            json={"recommendation_id": str(RECOMMENDATION_ID), "reason": "looks_bad"},
            headers=HEADERS,
        )
        assert response.status_code == 409
        assert response.json()["error"] == "no_candidates"


class TestOwnership:
    """The closest thing this app has to authorization."""

    async def test_another_session_cannot_read_a_decision(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stub(monkeypatch, "get_state", RequestNotFound("nope"))
        response = await client.get(f"/api/v1/decisions/{REQUEST_ID}", headers=HEADERS)

        assert response.status_code == 404
        assert response.json()["error"] == "not_found"

    async def test_another_session_cannot_reject(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stub(monkeypatch, "reject_and_next", RequestNotFound("nope"))
        response = await client.post(
            f"/api/v1/decisions/{REQUEST_ID}/reject",
            json={"recommendation_id": str(RECOMMENDATION_ID), "reason": "looks_bad"},
            headers=HEADERS,
        )
        assert response.status_code == 404

    async def test_another_session_cannot_accept(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stub(monkeypatch, "accept_recommendation", RequestNotFound("nope"))
        response = await client.post(
            f"/api/v1/decisions/{REQUEST_ID}/accept",
            json={"recommendation_id": str(RECOMMENDATION_ID)},
            headers=HEADERS,
        )
        assert response.status_code == 404

    async def test_a_404_never_reveals_that_the_request_exists(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stub(monkeypatch, "get_state", RequestNotFound(str(REQUEST_ID)))
        body = (await client.get(f"/api/v1/decisions/{REQUEST_ID}", headers=HEADERS)).json()
        assert str(REQUEST_ID) not in str(body)

    async def test_a_recommendation_from_a_different_request_is_refused(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stub(monkeypatch, "accept_recommendation", RecommendationMismatch("nope"))
        response = await client.post(
            f"/api/v1/decisions/{REQUEST_ID}/accept",
            json={"recommendation_id": str(RECOMMENDATION_ID)},
            headers=HEADERS,
        )
        assert response.status_code == 400
        assert response.json()["error"] == "recommendation_mismatch"


class TestAccept:
    async def test_confirms_the_choice(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stub(monkeypatch, "accept_recommendation", movie_view())
        response = await client.post(
            f"/api/v1/decisions/{REQUEST_ID}/accept",
            json={"recommendation_id": str(RECOMMENDATION_ID)},
            headers=HEADERS,
        )

        assert response.status_code == 200
        assert response.json() == {
            "status": "accepted",
            "movie": response.json()["movie"],
        }
        assert response.json()["movie"]["title"] == "Inception"

    async def test_a_second_verdict_is_refused_rather_than_silently_ignored(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A double tap or a retried request will do this; it must not overwrite."""
        stub(monkeypatch, "accept_recommendation", AlreadyDecided("nope"))
        response = await client.post(
            f"/api/v1/decisions/{REQUEST_ID}/accept",
            json={"recommendation_id": str(RECOMMENDATION_ID)},
            headers=HEADERS,
        )
        assert response.status_code == 409
        assert response.json()["error"] == "already_decided"


class TestReadState:
    async def test_returns_the_current_standing(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stub(monkeypatch, "get_state", state())
        body = (await client.get(f"/api/v1/decisions/{REQUEST_ID}", headers=HEADERS)).json()

        assert body["status"] == "pending"
        assert body["attempt"] == 2
        assert body["movie"]["title"] == "Inception"

    async def test_handles_a_request_that_never_produced_a_movie(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stub(
            monkeypatch,
            "get_state",
            state(status="empty", attempt=0, recommendation_id=None, movie=None),
        )
        body = (await client.get(f"/api/v1/decisions/{REQUEST_ID}", headers=HEADERS)).json()
        assert body["movie"] is None
        assert body["recommendation_id"] is None


class TestUpstreamFailures:
    async def test_a_slow_or_down_movie_source_is_a_503(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Retryable, so the client can reasonably try again."""
        stub(monkeypatch, "start", UpstreamUnavailable("timeout"))
        response = await client.post("/api/v1/decisions", json=VALID_BODY, headers=HEADERS)

        assert response.status_code == 503
        assert response.json()["error"] == "upstream_unavailable"

    async def test_our_own_credential_or_query_bug_is_a_502_not_a_4xx(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Blaming the caller for our misconfiguration would be a lie."""
        stub(monkeypatch, "start", UpstreamFailure("bad token"))
        response = await client.post("/api/v1/decisions", json=VALID_BODY, headers=HEADERS)

        assert response.status_code == 502
        assert response.json()["error"] == "upstream_failure"

    async def test_upstream_errors_never_leak_internals(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stub(monkeypatch, "start", UpstreamFailure("Bearer eyJhbGciOiJIUzI1NiJ9.secret"))
        body = (
            await client.post("/api/v1/decisions", json=VALID_BODY, headers=HEADERS)
        ).json()
        assert "eyJhbGci" not in str(body)
