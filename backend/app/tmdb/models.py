"""Typed views of TMDb responses.

Deliberately separate from the engine's CandidateMovie: this layer's job is to describe
what TMDb actually sends, including the parts the engine has no use for (posters,
overviews) and the parts it does not send at all.
"""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class TMDbGenre:
    """A genre as TMDb defines it."""

    id: int
    name: str


@dataclass(frozen=True, slots=True)
class TMDbProvider:
    """A streaming service. `logo_path` is a bare path needing a base URL prepended."""

    id: int
    name: str
    logo_path: str | None


@dataclass(frozen=True, slots=True)
class DiscoverMovie:
    """One result from /discover/movie.

    Note what is missing: **runtime** and **which** provider carries it. Discover filters
    on both but returns neither, so those come from /movie/{id} for the chosen film only.
    """

    tmdb_id: int
    title: str
    overview: str
    genre_ids: frozenset[int]
    vote_average: float
    vote_count: int
    popularity: float
    release_date: date | None
    poster_path: str | None
    backdrop_path: str | None
    original_language: str | None
    adult: bool


@dataclass(frozen=True, slots=True)
class DiscoverPage:
    """One page of search results, with the totals TMDb reports for the whole query.

    `total_results` is what the relaxation hints are read from: it is the count for the
    entire query, not just this page.
    """

    page: int
    total_pages: int
    total_results: int
    movies: tuple[DiscoverMovie, ...]


@dataclass(frozen=True, slots=True)
class MovieDetails:
    """/movie/{id} with watch providers appended — everything needed to render a result."""

    tmdb_id: int
    title: str
    overview: str
    runtime_minutes: int | None
    release_date: date | None
    vote_average: float
    vote_count: int
    poster_path: str | None
    backdrop_path: str | None
    genres: tuple[TMDbGenre, ...]
    flatrate_providers: tuple[TMDbProvider, ...]
    adult: bool

    @property
    def genre_ids(self) -> frozenset[int]:
        """Just the genre ids, for comparing against a request."""
        return frozenset(g.id for g in self.genres)

    @property
    def provider_ids(self) -> frozenset[int]:
        """Just the subscription-service ids, for comparing against a request."""
        return frozenset(p.id for p in self.flatrate_providers)
