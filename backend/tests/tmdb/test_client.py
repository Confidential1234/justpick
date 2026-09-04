"""Client behaviour: what it sends, and how it behaves when TMDb misbehaves."""

import httpx
import pytest

from app.tmdb.client import NETFLIX, PRIME_VIDEO, DiscoverFilters
from app.tmdb.errors import TMDbAuthError, TMDbRequestError, TMDbUnavailable

from .conftest import always, client_for, load

BOTH = frozenset({NETFLIX, PRIME_VIDEO})


class TestRequests:
    async def test_sends_the_bearer_token(self) -> None:
        client, transport = client_for(always(load("genres")))
        async with client:
            await client.genres()
        assert transport.last.headers["Authorization"] == "Bearer test-token"

    async def test_discover_hits_the_right_path_with_the_right_params(self) -> None:
        client, transport = client_for(always(load("discover_page")))
        async with client:
            await client.discover(
                DiscoverFilters(provider_ids=BOTH, genre_ids=frozenset({28}), max_runtime=120),
                page=2,
            )
        url = transport.last.url
        assert url.path == "/3/discover/movie"
        assert url.params["with_watch_providers"] == "8|9"
        assert url.params["with_genres"] == "28"
        assert url.params["with_runtime.lte"] == "120"
        assert url.params["page"] == "2"

    async def test_details_asks_for_providers_in_the_same_round_trip(self) -> None:
        client, transport = client_for(always(load("movie_details")))
        async with client:
            details = await client.movie_details(27205)
        assert transport.last.url.path == "/3/movie/27205"
        assert transport.last.url.params["append_to_response"] == "watch/providers"
        assert details.runtime_minutes is not None
        assert details.flatrate_providers

    async def test_discover_returns_parsed_movies(self) -> None:
        client, _ = client_for(always(load("discover_page")))
        async with client:
            page = await client.discover(DiscoverFilters(provider_ids=BOTH))
        assert len(page.movies) == 5
        assert page.total_results > 0

    async def test_watch_providers_are_parsed(self) -> None:
        client, _ = client_for(always(load("watch_providers_us")))
        async with client:
            providers = await client.watch_providers()
        assert {p.id for p in providers} >= {NETFLIX, PRIME_VIDEO}


class TestErrorHandling:
    async def test_bad_token_raises_immediately(self, no_sleep: list[float]) -> None:
        client, transport = client_for(always({"status_message": "Invalid API key"}, status=401))
        async with client:
            with pytest.raises(TMDbAuthError):
                await client.genres()
        assert transport.call_count == 1, "an auth failure must not be retried"

    async def test_a_bad_request_is_not_retried(self, no_sleep: list[float]) -> None:
        """A 4xx is our bug. Retrying an invalid filter just sends it again."""
        client, transport = client_for(always({"status_message": "Invalid page"}, status=400))
        async with client:
            with pytest.raises(TMDbRequestError) as exc:
                await client.genres()
        assert transport.call_count == 1
        assert exc.value.status_code == 400
        assert "Invalid page" in exc.value.message

    async def test_server_errors_are_retried_then_give_up(self, no_sleep: list[float]) -> None:
        client, transport = client_for(always({}, status=503), max_retries=2)
        async with client:
            with pytest.raises(TMDbUnavailable):
                await client.genres()
        assert transport.call_count == 3  # the original plus two retries

    async def test_a_transient_failure_recovers(self, no_sleep: list[float]) -> None:
        calls = {"n": 0}

        def flaky(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] == 1:
                return httpx.Response(500, json={})
            return httpx.Response(200, json=load("genres"))

        client, transport = client_for(flaky)
        async with client:
            genres = await client.genres()
        assert transport.call_count == 2
        assert len(genres) == 19

    async def test_timeouts_surface_as_unavailable(self, no_sleep: list[float]) -> None:
        def timing_out(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectTimeout("too slow", request=request)

        client, transport = client_for(timing_out, max_retries=1)
        async with client:
            with pytest.raises(TMDbUnavailable):
                await client.genres()
        assert transport.call_count == 2


class TestBackoff:
    async def test_waits_longer_after_each_failure(self, no_sleep: list[float]) -> None:
        client, _ = client_for(always({}, status=500), max_retries=3, backoff_base=0.5)
        async with client:
            with pytest.raises(TMDbUnavailable):
                await client.genres()
        assert no_sleep == [0.5, 1.0, 2.0], "expected exponential backoff"

    async def test_does_not_sleep_after_the_final_attempt(self, no_sleep: list[float]) -> None:
        """Sleeping before giving up just delays the error."""
        client, _ = client_for(always({}, status=500), max_retries=1, backoff_base=0.5)
        async with client:
            with pytest.raises(TMDbUnavailable):
                await client.genres()
        assert no_sleep == [0.5]

    async def test_respects_retry_after_when_it_is_longer(self, no_sleep: list[float]) -> None:
        def rate_limited(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, json={}, headers={"Retry-After": "7"})

        client, _ = client_for(rate_limited, max_retries=1, backoff_base=0.5)
        async with client:
            with pytest.raises(TMDbUnavailable):
                await client.genres()
        assert no_sleep == [7.0]

    async def test_ignores_an_unparseable_retry_after(self, no_sleep: list[float]) -> None:
        http_date = "Wed, 21 Oct 2026 07:28:00 GMT"

        def rate_limited(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, json={}, headers={"Retry-After": http_date})

        client, _ = client_for(rate_limited, max_retries=1, backoff_base=0.5)
        async with client:
            with pytest.raises(TMDbUnavailable):
                await client.genres()
        assert no_sleep == [0.5]
