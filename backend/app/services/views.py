"""Presentation-shaped values assembled by the service layer.

One movie view built from two sources — a fresh TMDb details payload, or a cached row —
so the API renders a chosen film and a re-read of an earlier decision identically.
"""

from dataclasses import dataclass
from typing import Any, Protocol

from app.config import get_settings
from app.tmdb.models import MovieDetails

TMDB_MOVIE_URL = "https://www.themoviedb.org/movie/{id}"
POSTER_SIZE = "w500"


@dataclass(frozen=True, slots=True)
class GenreOption:
    id: int
    name: str


@dataclass(frozen=True, slots=True)
class ProviderOption:
    id: int
    name: str
    logo_url: str | None


@dataclass(frozen=True, slots=True)
class MovieView:
    tmdb_id: int
    title: str
    overview: str
    release_year: int | None
    runtime_minutes: int | None
    vote_average: float
    vote_count: int
    poster_url: str | None
    genres: tuple[GenreOption, ...]
    providers: tuple[ProviderOption, ...]
    tmdb_url: str


class _MovieRow(Protocol):
    """Just enough of the ORM row to build a view, without importing app.db here."""

    tmdb_id: int
    title: str
    overview: Any
    release_date: Any
    runtime_minutes: Any
    vote_average: Any
    vote_count: int
    poster_path: Any


def image_url(path: str | None, size: str = POSTER_SIZE) -> str | None:
    if not path:
        return None
    return f"{get_settings().tmdb_image_base_url}/{size}{path}"


def _view(
    *,
    tmdb_id: int,
    title: str,
    overview: str,
    release_year: int | None,
    runtime_minutes: int | None,
    vote_average: float,
    vote_count: int,
    poster_path: str | None,
    genres: tuple[GenreOption, ...],
    providers: tuple[ProviderOption, ...],
) -> MovieView:
    return MovieView(
        tmdb_id=tmdb_id,
        title=title,
        overview=overview,
        release_year=release_year,
        runtime_minutes=runtime_minutes,
        # TMDb returns full precision (7.459) while the cached column is Numeric(3,1).
        # Rounding here keeps a fresh pick and a re-read of the same pick identical.
        vote_average=round(vote_average, 1),
        vote_count=vote_count,
        poster_url=image_url(poster_path),
        genres=genres,
        providers=providers,
        tmdb_url=TMDB_MOVIE_URL.format(id=tmdb_id),
    )


def from_details(
    details: MovieDetails,
    providers: tuple[ProviderOption, ...],
) -> MovieView:
    return _view(
        tmdb_id=details.tmdb_id,
        title=details.title,
        overview=details.overview,
        release_year=details.release_date.year if details.release_date else None,
        runtime_minutes=details.runtime_minutes,
        vote_average=float(details.vote_average),
        vote_count=details.vote_count,
        poster_path=details.poster_path,
        genres=tuple(GenreOption(id=g.id, name=g.name) for g in details.genres),
        providers=providers,
    )


def from_row(
    row: _MovieRow,
    genres: tuple[GenreOption, ...],
    providers: tuple[ProviderOption, ...],
) -> MovieView:
    return _view(
        tmdb_id=row.tmdb_id,
        title=row.title,
        overview=row.overview or "",
        release_year=row.release_date.year if row.release_date else None,
        runtime_minutes=row.runtime_minutes,
        vote_average=float(row.vote_average or 0),
        vote_count=row.vote_count,
        poster_path=row.poster_path,
        genres=genres,
        providers=providers,
    )
