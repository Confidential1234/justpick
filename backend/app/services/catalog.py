"""Candidate sourcing: TMDb for breadth, the cache for the parts TMDb leaves out."""

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy.ext.asyncio import AsyncSession

from app.engine.models import CandidateMovie, Constraint, DecisionRequest
from app.repositories import catalog as repo
from app.services.errors import UpstreamFailure, UpstreamUnavailable
from app.services.views import (
    GenreOption,
    MovieView,
    ProviderOption,
    from_row,
    image_url,
)
from app.tmdb.client import DiscoverFilters, TMDbClient
from app.tmdb.errors import TMDbAuthError, TMDbRequestError, TMDbUnavailable
from app.tmdb.mappers import to_candidate
from app.tmdb.models import DiscoverMovie, MovieDetails

PAGES = 3


@contextmanager
def _upstream() -> Iterator[None]:
    """Translate TMDb failures into service-level ones.

    Keeps the name of the movie source out of everything above this layer — swapping
    provider should not touch the API's error handling.
    """
    try:
        yield
    except TMDbUnavailable as exc:
        raise UpstreamUnavailable(str(exc)) from exc
    except (TMDbAuthError, TMDbRequestError) as exc:
        raise UpstreamFailure(str(exc)) from exc


def _filters(request: DecisionRequest, region: str = "US") -> DiscoverFilters:
    return DiscoverFilters(
        provider_ids=request.provider_ids,
        genre_ids=request.genre_ids,
        max_runtime=request.max_runtime,
        min_rating=request.min_rating,
        region=region,
    )


def _movie_row(movie: DiscoverMovie) -> dict[str, object]:
    return {
        "tmdb_id": movie.tmdb_id,
        "title": movie.title,
        "overview": movie.overview,
        "release_date": movie.release_date,
        "vote_average": movie.vote_average,
        "vote_count": movie.vote_count,
        "popularity": movie.popularity,
        "poster_path": movie.poster_path,
        "backdrop_path": movie.backdrop_path,
        "original_language": movie.original_language,
        "adult": movie.adult,
    }


async def fetch_candidates(
    client: TMDbClient, db: AsyncSession, request: DecisionRequest, region: str = "US"
) -> list[CandidateMovie]:
    """Pull candidates from TMDb, cache them, and enrich with anything already known.

    The enrichment is the interesting half. Discover never returns runtimes, so a movie
    the app has never chosen scores a neutral runtime_fit. Every details call for a
    chosen film records one, so that component does progressively more work as the cache
    warms rather than being permanently inert.
    """
    filters = _filters(request, region)
    with _upstream():
        first = await client.discover(filters, page=1)
        remaining = range(2, min(PAGES, first.total_pages) + 1)
        others = await asyncio.gather(*(client.discover(filters, page=n) for n in remaining))

    unique: dict[int, DiscoverMovie] = {}
    for page in (first, *others):
        for movie in page.movies:
            unique.setdefault(movie.tmdb_id, movie)

    if not unique:
        return []

    await repo.upsert_movies(db, [_movie_row(m) for m in unique.values()])
    await repo.link_genres(
        db, [(m.tmdb_id, genre_id) for m in unique.values() for genre_id in m.genre_ids]
    )

    runtimes = await repo.cached_runtimes(db, list(unique))
    return [
        to_candidate(movie, request.provider_ids, runtime_minutes=runtimes.get(movie.tmdb_id))
        for movie in unique.values()
    ]


async def hydrate(
    client: TMDbClient, db: AsyncSession, tmdb_id: int, region: str = "US"
) -> MovieDetails:
    """Fetch the chosen film's runtime and availability, and remember both."""
    with _upstream():
        details = await client.movie_details(tmdb_id, region=region)
    await repo.set_movie_details(db, tmdb_id, details.runtime_minutes)
    await repo.record_availability(db, tmdb_id, sorted(details.provider_ids), region=region)
    return details


async def relaxation_counts(
    client: TMDbClient, request: DecisionRequest, region: str = "US"
) -> dict[Constraint, int]:
    """How many movies each single relaxation would unlock, straight from TMDb.

    The engine cannot answer this. Discover applies the filters server-side, so a request
    that returns nothing also returns no near-misses to count — precisely the case the
    hints exist for. One extra query per relaxable constraint reads TMDb's own
    total_results, which is both exact and bounded at three calls.
    """
    variants: dict[Constraint, DiscoverFilters] = {}
    base = _filters(request, region)

    if request.min_rating is not None:
        variants[Constraint.RATING] = DiscoverFilters(**{**vars_of(base), "min_rating": None})
    variants[Constraint.RUNTIME] = DiscoverFilters(**{**vars_of(base), "max_runtime": None})
    if request.genre_ids:
        variants[Constraint.GENRE] = DiscoverFilters(
            **{**vars_of(base), "genre_ids": frozenset()}
        )

    # return_exceptions: a hint that cannot be computed is a missing suggestion, not a
    # failed request. The user is already looking at an empty result.
    pages = await asyncio.gather(
        *(client.discover(f, page=1) for f in variants.values()), return_exceptions=True
    )
    counts: dict[Constraint, int] = {}
    for constraint, page in zip(variants, pages, strict=True):
        if not isinstance(page, BaseException):
            counts[constraint] = page.total_results
    return counts


def vars_of(filters: DiscoverFilters) -> dict[str, object]:
    """dataclasses.asdict would deep-copy the frozensets; this keeps them as-is."""
    return {field: getattr(filters, field) for field in filters.__slots__}


# ------------------------------------------------------------------ reference lookups


async def list_providers(db: AsyncSession) -> list[ProviderOption]:
    """The services the UI offers. Only the enabled ones, not TMDb's full list of ~290."""
    return [
        ProviderOption(id=p.id, name=p.name, logo_url=image_url(p.logo_path, size="original"))
        for p in await repo.enabled_providers(db)
    ]


async def list_genres(db: AsyncSession) -> list[GenreOption]:
    return [GenreOption(id=g.id, name=g.name) for g in await repo.all_genres(db)]


async def movie_view(
    db: AsyncSession, tmdb_id: int, provider_ids: frozenset[int], region: str = "US"
) -> MovieView | None:
    """Rebuild a movie's presentation from the cache, for re-reading an earlier decision."""
    row = await repo.get_movie(db, tmdb_id)
    if row is None:
        return None
    genres = tuple(
        GenreOption(id=g.id, name=g.name) for g in await repo.genres_for_movie(db, tmdb_id)
    )
    providers = tuple(
        ProviderOption(id=p.id, name=p.name, logo_url=image_url(p.logo_path, size="original"))
        for p in await repo.providers_for_movie(db, tmdb_id, sorted(provider_ids), region)
    )
    return from_row(row, genres, providers)
