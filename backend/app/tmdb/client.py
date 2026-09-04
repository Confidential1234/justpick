"""Async TMDb client.

Encapsulates every fact about TMDb's wire format so nothing above this layer has to know
them — including the ones that are easy to get wrong, like comma meaning AND in
`with_genres` while pipe means OR.
"""

import asyncio
import contextlib
from dataclasses import dataclass
from typing import Any

import httpx

from app.tmdb.errors import TMDbAuthError, TMDbRequestError, TMDbUnavailable
from app.tmdb.mappers import (
    parse_discover_page,
    parse_genre,
    parse_movie_details,
    parse_provider,
)
from app.tmdb.models import DiscoverPage, MovieDetails, TMDbGenre, TMDbProvider

DEFAULT_BASE_URL = "https://api.themoviedb.org/3"
DEFAULT_REGION = "US"

# Verified against the live API: including the ad-supported tiers as well
# (1796 Netflix with Ads, 2100/613 Prime with Ads) moves the pool 5,536 -> 5,653, so the
# extra provider ids are not worth carrying.
NETFLIX = 8
PRIME_VIDEO = 9

# Anything scored is worth at least this many votes; below it a high average is usually a
# handful of enthusiastic voters rather than a good film.
DEFAULT_MIN_VOTE_COUNT = 100


@dataclass(frozen=True, slots=True)
class DiscoverFilters:
    provider_ids: frozenset[int]
    genre_ids: frozenset[int] = frozenset()
    max_runtime: int | None = None
    min_rating: float | None = None
    min_vote_count: int = DEFAULT_MIN_VOTE_COUNT
    region: str = DEFAULT_REGION

    def as_params(self) -> dict[str, str]:
        params: dict[str, str] = {
            "watch_region": self.region,
            "with_watch_monetization_types": "flatrate",
            "include_adult": "false",
            "sort_by": "popularity.desc",
            # Pipe is OR, comma is AND. Verified: for Action + Sci-Fi on Netflix/Prime,
            # "28,878" returns 196 results and "28|878" returns 1,410.
            "with_watch_providers": "|".join(str(p) for p in sorted(self.provider_ids)),
        }
        if self.genre_ids:
            params["with_genres"] = "|".join(str(g) for g in sorted(self.genre_ids))
        if self.max_runtime is not None:
            params["with_runtime.lte"] = str(self.max_runtime)
        if self.min_rating is not None:
            params["vote_average.gte"] = str(self.min_rating)
        # TMDb answers 400 to vote_count.gte=0, so omit rather than send a zero floor.
        if self.min_vote_count > 0:
            params["vote_count.gte"] = str(self.min_vote_count)
        return params


class TMDbClient:
    """Thin async wrapper. One instance per application, reused across requests."""

    def __init__(
        self,
        token: str,
        base_url: str = DEFAULT_BASE_URL,
        *,
        timeout: float = 10.0,
        max_retries: int = 2,
        backoff_base: float = 0.5,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout,
            transport=transport,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
        )

    async def __aenter__(self) -> "TMDbClient":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _get(self, path: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        last_error: Exception | None = None

        for attempt in range(self._max_retries + 1):
            try:
                response = await self._client.get(path, params=params)
            except httpx.HTTPError as exc:  # timeouts, DNS, connection resets
                last_error = exc
                await self._backoff(attempt)
                continue

            if response.status_code == 401:
                raise TMDbAuthError("TMDb rejected the token")

            if response.status_code == 429:
                last_error = TMDbUnavailable("rate limited")
                await self._backoff(attempt, retry_after=response.headers.get("Retry-After"))
                continue

            if response.status_code >= 500:
                last_error = TMDbUnavailable(f"TMDb returned {response.status_code}")
                await self._backoff(attempt)
                continue

            if response.status_code >= 400:
                # A 4xx is our bug — a malformed filter, say. Retrying just repeats it.
                raise TMDbRequestError(response.status_code, _error_message(response))

            return response.json()

        raise TMDbUnavailable(f"TMDb unreachable after {self._max_retries + 1} attempts") from (
            last_error
        )

    async def _backoff(self, attempt: int, retry_after: str | None = None) -> None:
        if attempt >= self._max_retries:
            return  # last attempt: fall through to the raise rather than sleeping first
        delay = self._backoff_base * (2**attempt)
        if retry_after:
            # Retry-After may also be an HTTP date, which we do not honour — the
            # exponential delay is a fine fallback and dates from TMDb are rare.
            with contextlib.suppress(ValueError):
                delay = max(delay, float(retry_after))
        if delay > 0:
            await asyncio.sleep(delay)

    async def genres(self, language: str = "en-US") -> tuple[TMDbGenre, ...]:
        payload = await self._get("/genre/movie/list", {"language": language})
        return tuple(parse_genre(g) for g in payload.get("genres") or ())

    async def watch_providers(self, region: str = DEFAULT_REGION) -> tuple[TMDbProvider, ...]:
        payload = await self._get("/watch/providers/movie", {"watch_region": region})
        return tuple(parse_provider(p) for p in payload.get("results") or ())

    async def discover(self, filters: DiscoverFilters, page: int = 1) -> DiscoverPage:
        params = filters.as_params() | {"page": str(page)}
        return parse_discover_page(await self._get("/discover/movie", params))

    async def movie_details(
        self, tmdb_id: int, region: str = DEFAULT_REGION
    ) -> MovieDetails:
        """Runtime, genres and streaming availability in a single round trip."""
        payload = await self._get(
            f"/movie/{tmdb_id}", {"append_to_response": "watch/providers"}
        )
        return parse_movie_details(payload, region=region)


def _error_message(response: httpx.Response) -> str:
    try:
        return str(response.json().get("status_message", response.text[:200]))
    except ValueError:
        return response.text[:200]
