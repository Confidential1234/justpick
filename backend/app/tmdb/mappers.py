"""Parsing TMDb JSON into typed objects, and typed objects into engine candidates.

Every field TMDb sends is treated as optional. Their catalogue is community-maintained
and half-populated rows are normal, so a missing poster or release date must degrade the
result rather than raise.
"""

from datetime import date
from typing import Any

from app.engine.models import CandidateMovie
from app.tmdb.models import (
    DiscoverMovie,
    DiscoverPage,
    MovieDetails,
    TMDbGenre,
    TMDbProvider,
)


def _parse_date(value: Any) -> date | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _as_float(value: Any, default: float = 0.0) -> float:
    return float(value) if isinstance(value, int | float) else default


def _as_int(value: Any, default: int = 0) -> int:
    return int(value) if isinstance(value, int | float) else default


def parse_genre(raw: dict[str, Any]) -> TMDbGenre:
    return TMDbGenre(id=int(raw["id"]), name=str(raw.get("name", "")))


def parse_provider(raw: dict[str, Any]) -> TMDbProvider:
    return TMDbProvider(
        id=int(raw["provider_id"]),
        name=str(raw.get("provider_name", "")),
        logo_path=raw.get("logo_path"),
    )


def parse_discover_movie(raw: dict[str, Any]) -> DiscoverMovie:
    return DiscoverMovie(
        tmdb_id=int(raw["id"]),
        title=str(raw.get("title") or raw.get("original_title") or ""),
        overview=str(raw.get("overview") or ""),
        genre_ids=frozenset(int(g) for g in raw.get("genre_ids") or ()),
        vote_average=_as_float(raw.get("vote_average")),
        vote_count=_as_int(raw.get("vote_count")),
        popularity=_as_float(raw.get("popularity")),
        release_date=_parse_date(raw.get("release_date")),
        poster_path=raw.get("poster_path"),
        backdrop_path=raw.get("backdrop_path"),
        original_language=raw.get("original_language"),
        adult=bool(raw.get("adult", False)),
    )


def parse_discover_page(raw: dict[str, Any]) -> DiscoverPage:
    return DiscoverPage(
        page=_as_int(raw.get("page"), 1),
        total_pages=_as_int(raw.get("total_pages")),
        total_results=_as_int(raw.get("total_results")),
        movies=tuple(parse_discover_movie(m) for m in raw.get("results") or ()),
    )


def parse_movie_details(raw: dict[str, Any], region: str = "US") -> MovieDetails:
    """Parse /movie/{id}?append_to_response=watch/providers.

    Only `flatrate` providers are kept. Rent and buy entries are also present in that
    payload, and a film you would have to pay for again is not one you already have
    access to — including them would break the core promise of the app.
    """
    providers_block = raw.get("watch/providers") or {}
    regional = (providers_block.get("results") or {}).get(region) or {}
    flatrate = regional.get("flatrate") or []

    return MovieDetails(
        tmdb_id=int(raw["id"]),
        title=str(raw.get("title") or raw.get("original_title") or ""),
        overview=str(raw.get("overview") or ""),
        runtime_minutes=int(raw["runtime"]) if raw.get("runtime") else None,
        release_date=_parse_date(raw.get("release_date")),
        vote_average=_as_float(raw.get("vote_average")),
        vote_count=_as_int(raw.get("vote_count")),
        poster_path=raw.get("poster_path"),
        backdrop_path=raw.get("backdrop_path"),
        genres=tuple(parse_genre(g) for g in raw.get("genres") or ()),
        flatrate_providers=tuple(parse_provider(p) for p in flatrate),
        adult=bool(raw.get("adult", False)),
    )


def to_candidate(
    movie: DiscoverMovie,
    requested_provider_ids: frozenset[int],
    runtime_minutes: int | None = None,
) -> CandidateMovie:
    """Adapt a discover result into something the engine can score.

    `requested_provider_ids` is carried through rather than looked up: discover was asked
    to return only films on those services, so TMDb has already made the guarantee that
    the engine's PROVIDER constraint checks. Which specific service carries it is a
    display question, answered later by the details call for the chosen film.

    `runtime_minutes` stays None unless a caller supplies it from cache. Discover does not
    return runtimes, and fetching them for every candidate would cost one request each.
    """
    return CandidateMovie(
        tmdb_id=movie.tmdb_id,
        title=movie.title,
        genre_ids=movie.genre_ids,
        provider_ids=requested_provider_ids,
        vote_average=movie.vote_average,
        vote_count=movie.vote_count,
        runtime_minutes=runtime_minutes,
        release_date=movie.release_date,
        adult=movie.adult,
    )
