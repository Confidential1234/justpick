"""Request and response bodies. The only place the wire format is defined."""

import uuid

from pydantic import BaseModel, Field, field_validator

MIN_RUNTIME = 40
MAX_RUNTIME = 300
# Cinema's first feature-length films; anything earlier is a data error, not a preference.
EARLIEST_YEAR = 1900


class GenreOut(BaseModel):
    """A genre, for the mood picker or a movie's own tags."""

    id: int
    name: str


class ProviderOut(BaseModel):
    """A streaming service, with a full logo URL ready to render."""

    id: int
    name: str
    logo_url: str | None = None


class MovieOut(BaseModel):
    """A movie as the frontend renders it. `providers` lists only the user's services."""

    tmdb_id: int
    title: str
    overview: str
    release_year: int | None
    runtime_minutes: int | None
    vote_average: float
    vote_count: int
    poster_url: str | None
    genres: list[GenreOut]
    providers: list[ProviderOut]
    tmdb_url: str


class DecisionCreate(BaseModel):
    """The constraints a user submits. At least one provider is required.

    Genres, rating and year are all optional; runtime is not, because "how long have you
    got" is the question the app is built around.
    """

    provider_ids: list[int] = Field(min_length=1)
    genre_ids: list[int] = Field(default_factory=list)
    max_runtime: int = Field(ge=MIN_RUNTIME, le=MAX_RUNTIME)
    min_rating: float | None = Field(default=None, ge=0, le=10)
    # Oldest acceptable release year; null means no floor.
    min_year: int | None = Field(default=None, ge=EARLIEST_YEAR, le=2100)

    @field_validator("provider_ids", "genre_ids")
    @classmethod
    def _dedupe(cls, value: list[int]) -> list[int]:
        return sorted(set(value))


class RejectIn(BaseModel):
    """A rejection. The reason is required — it is the app's most useful signal."""

    recommendation_id: uuid.UUID
    reason: str
    note: str | None = Field(default=None, max_length=500)


class AcceptIn(BaseModel):
    """An acceptance. The recommendation id guards against acting on a stale screen."""

    recommendation_id: uuid.UUID


class HighlightOut(BaseModel):
    """One score component and its weighted contribution to the total."""

    component: str
    contribution: float


class DecisionOut(BaseModel):
    """A successful decision: the movie, why it was picked, and how many options remain."""

    request_id: uuid.UUID
    recommendation_id: uuid.UUID
    attempt: int
    movie: MovieOut
    why: list[str]
    highlights: list[HighlightOut]
    candidates_remaining: int


class AcceptedOut(BaseModel):
    """Confirmation that the user is watching this one."""

    status: str = "accepted"
    movie: MovieOut


class RelaxationHint(BaseModel):
    """One thing the user could loosen, and what it would buy them.

    `would_yield` is the total matching the relaxed query, not an increment — it is read
    straight from TMDb's own result count.
    """

    field: str
    action: str
    label: str
    would_yield: int


class ErrorOut(BaseModel):
    """The single error shape every failure uses, so clients parse one format.

    `relaxation_hints` is populated only for a no-candidates 409.
    """

    error: str
    message: str
    relaxation_hints: list[RelaxationHint] = Field(default_factory=list)
