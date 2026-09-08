"""ORM models.

Two groups with different lifetimes. `providers`/`genres`/`movies`/`movie_genres`/
`movie_providers` are a cache of TMDb and can be rebuilt from the API at any time.
`sessions`/`decision_requests`/`recommendations`/`feedback` are ours and cannot.
"""

import uuid
from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Enum as SAEnum
from sqlalchemy.types import Uuid

from app.db.base import Base


class FeedbackAction(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class RejectReason(StrEnum):
    ALREADY_SEEN = "already_seen"
    NOT_IN_THE_MOOD = "not_in_the_mood"
    TOO_LONG = "too_long"
    WRONG_GENRE = "wrong_genre"
    LOOKS_BAD = "looks_bad"
    OTHER = "other"


def _now() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


def _enum_values(enum_cls: type[StrEnum]) -> list[str]:
    return [member.value for member in enum_cls]


# --------------------------------------------------------------------------- catalogue


class Provider(Base):
    __tablename__ = "providers"

    # TMDb's own id, not ours: 8 = Netflix, 9 = Amazon Prime Video.
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    logo_path: Mapped[str | None] = mapped_column(Text)
    # Lets us stock the table from TMDb's full list while only offering the supported ones.
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class Genre(Base):
    __tablename__ = "genres"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)


class Movie(Base):
    __tablename__ = "movies"

    tmdb_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    original_title: Mapped[str | None] = mapped_column(Text)
    overview: Mapped[str | None] = mapped_column(Text)
    release_date: Mapped[date | None] = mapped_column(Date)
    # Null until a details call fills it in; discover does not return runtimes.
    runtime_minutes: Mapped[int | None] = mapped_column(Integer)
    vote_average: Mapped[float] = mapped_column(Numeric(3, 1), nullable=False, default=0)
    vote_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    popularity: Mapped[float] = mapped_column(Numeric(10, 3), nullable=False, default=0)
    poster_path: Mapped[str | None] = mapped_column(Text)
    backdrop_path: Mapped[str | None] = mapped_column(Text)
    original_language: Mapped[str | None] = mapped_column(String(16))
    adult: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    details_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = _now()

    genres: Mapped[list["MovieGenre"]] = relationship(
        back_populates="movie", cascade="all, delete-orphan", lazy="selectin"
    )
    providers: Mapped[list["MovieProvider"]] = relationship(
        back_populates="movie", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        Index("ix_movies_runtime", "runtime_minutes"),
        Index("ix_movies_rating", "vote_average", "vote_count"),
    )


class MovieGenre(Base):
    __tablename__ = "movie_genres"

    movie_id: Mapped[int] = mapped_column(
        ForeignKey("movies.tmdb_id", ondelete="CASCADE"), primary_key=True
    )
    genre_id: Mapped[int] = mapped_column(ForeignKey("genres.id"), primary_key=True)

    movie: Mapped[Movie] = relationship(back_populates="genres")

    __table_args__ = (Index("ix_movie_genres_genre", "genre_id"),)


class MovieProvider(Base):
    __tablename__ = "movie_providers"

    movie_id: Mapped[int] = mapped_column(
        ForeignKey("movies.tmdb_id", ondelete="CASCADE"), primary_key=True
    )
    provider_id: Mapped[int] = mapped_column(ForeignKey("providers.id"), primary_key=True)
    region: Mapped[str] = mapped_column(String(2), primary_key=True, default="US")
    monetization_type: Mapped[str] = mapped_column(Text, primary_key=True, default="flatrate")
    # Availability churns constantly; metadata does not. Only this row gets a short TTL.
    last_verified_at: Mapped[datetime] = _now()

    movie: Mapped[Movie] = relationship(back_populates="providers")

    __table_args__ = (
        Index("ix_movie_providers_lookup", "provider_id", "region", "monetization_type"),
    )


# ---------------------------------------------------------------------------- activity


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = _now()
    last_seen_at: Mapped[datetime] = _now()
    user_agent: Mapped[str | None] = mapped_column(Text)


class DecisionRequestRow(Base):
    """One set of constraints. Rejections produce further attempts against the same row."""

    __tablename__ = "decision_requests"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    provider_ids: Mapped[list[int]] = mapped_column(ARRAY(Integer), nullable=False)
    genre_ids: Mapped[list[int]] = mapped_column(ARRAY(Integer), nullable=False, default=list)
    max_runtime: Mapped[int] = mapped_column(Integer, nullable=False)
    min_rating: Mapped[float | None] = mapped_column(Numeric(3, 1))
    min_year: Mapped[int | None] = mapped_column(Integer)
    region: Mapped[str] = mapped_column(String(2), nullable=False, default="US")
    created_at: Mapped[datetime] = _now()

    __table_args__ = (
        Index("ix_decision_requests_session", "session_id", "created_at"),
    )


class Recommendation(Base):
    __tablename__ = "recommendations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("decision_requests.id", ondelete="CASCADE"), nullable=False
    )
    movie_id: Mapped[int] = mapped_column(ForeignKey("movies.tmdb_id"), nullable=False)
    attempt: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    score: Mapped[float] = mapped_column(Numeric(6, 4), nullable=False)
    # Every sub-score, so a surprising pick can be explained after the fact rather than
    # re-derived from a scoring function that may have changed since.
    score_breakdown: Mapped[dict] = mapped_column(JSONB, nullable=False)
    candidate_count: Mapped[int] = mapped_column(Integer, nullable=False)
    band_size: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = _now()

    __table_args__ = (
        Index("uq_recommendations_attempt", "request_id", "attempt", unique=True),
        Index("ix_recommendations_movie", "movie_id"),
    )


class Feedback(Base):
    """Accepting or rejecting a recommendation.

    An event with a reason and a timestamp, not a boolean on the movie: the reason is the
    most useful signal this app collects. "too_long" against a 120-minute limit says the
    runtime weight is wrong, and a flag would throw that away.
    """

    __tablename__ = "feedback"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    recommendation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recommendations.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    movie_id: Mapped[int] = mapped_column(ForeignKey("movies.tmdb_id"), nullable=False)
    # values_callable stores the enum *values* ("accepted") rather than the member names
    # ("ACCEPTED"), which is what the CHECK constraint below compares against.
    action: Mapped[FeedbackAction] = mapped_column(
        SAEnum(FeedbackAction, name="feedback_action", values_callable=_enum_values),
        nullable=False,
    )
    reason: Mapped[RejectReason | None] = mapped_column(
        SAEnum(RejectReason, name="reject_reason", values_callable=_enum_values)
    )
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()

    __table_args__ = (
        CheckConstraint(
            "(action = 'rejected') = (reason IS NOT NULL)",
            name="ck_feedback_reason_iff_rejected",
        ),
        # Drives the exclusion lookup: everything this session has seen recently.
        Index("ix_feedback_session_movie", "session_id", "movie_id", "created_at"),
    )
