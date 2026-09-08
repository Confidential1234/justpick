"""Request and response bodies. The only place the wire format is defined."""

import uuid

from pydantic import BaseModel, Field, field_validator

MIN_RUNTIME = 40
MAX_RUNTIME = 300
# Cinema's first feature-length films; anything earlier is a data error, not a preference.
EARLIEST_YEAR = 1900


class GenreOut(BaseModel):
    id: int
    name: str


class ProviderOut(BaseModel):
    id: int
    name: str
    logo_url: str | None = None


class MovieOut(BaseModel):
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
    recommendation_id: uuid.UUID
    reason: str
    note: str | None = Field(default=None, max_length=500)


class AcceptIn(BaseModel):
    recommendation_id: uuid.UUID


class HighlightOut(BaseModel):
    component: str
    contribution: float


class DecisionOut(BaseModel):
    request_id: uuid.UUID
    recommendation_id: uuid.UUID
    attempt: int
    movie: MovieOut
    why: list[str]
    highlights: list[HighlightOut]
    candidates_remaining: int


class AcceptedOut(BaseModel):
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
    error: str
    message: str
    relaxation_hints: list[RelaxationHint] = Field(default_factory=list)
