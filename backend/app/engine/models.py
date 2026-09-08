"""Value types for the decision engine.

Deliberately plain: stdlib only, frozen, no ORM rows and no HTTP payloads. Anything
that wants to use the engine adapts its own data into these first, which is what keeps
the engine testable from literals.
"""

from dataclasses import dataclass
from datetime import date
from enum import StrEnum


class Constraint(StrEnum):
    """A hard requirement a movie can fail. Failing any one eliminates it."""

    PROVIDER = "provider"
    RUNTIME = "runtime"
    RATING = "rating"
    RELEASE_YEAR = "release_year"
    VOTE_COUNT = "vote_count"
    GENRE = "genre"
    EXCLUDED = "excluded"
    RELEASED = "released"
    ADULT = "adult"


class DecisionReason(StrEnum):
    """Why a decision turned out the way it did: a movie was found, or nothing qualified."""

    OK = "ok"
    NO_CANDIDATES = "no_candidates"


@dataclass(frozen=True, slots=True)
class CandidateMovie:
    """A movie the engine may return, reduced to only the fields it reasons about.

    `runtime_minutes` is optional because TMDb's discover endpoint does not return it;
    it is filled in from cache when known. `release_date` is optional because the
    catalogue is community-maintained and half-populated rows are normal.
    """

    tmdb_id: int
    title: str
    genre_ids: frozenset[int]
    provider_ids: frozenset[int]
    vote_average: float
    vote_count: int
    runtime_minutes: int | None = None
    release_date: date | None = None
    adult: bool = False


@dataclass(frozen=True, slots=True)
class DecisionRequest:
    """What the user asked for. Says nothing about who asked, or how many people did."""

    provider_ids: frozenset[int]
    genre_ids: frozenset[int]
    max_runtime: int
    min_rating: float | None = None
    # Oldest acceptable release year. A filter rather than an age penalty in scoring:
    # someone who wants a 1938 film should still be able to get one.
    min_year: int | None = None


@dataclass(frozen=True, slots=True)
class ScoreBreakdown:
    """Every component, kept separately so a surprising pick can be explained after the fact."""

    genre_match: float
    rating: float
    runtime_fit: float
    total: float


@dataclass(frozen=True, slots=True)
class ScoredMovie:
    """A candidate paired with its score, as produced by ranking."""

    movie: CandidateMovie
    breakdown: ScoreBreakdown


@dataclass(frozen=True, slots=True)
class Highlight:
    """The component that drove a pick, and how much of the total it contributed.

    Structured rather than prose: the engine has genre *ids*, not names, so rendering
    "Matches Action + Sci-Fi" is the API layer's job.
    """

    component: str
    contribution: float


@dataclass(frozen=True, slots=True)
class Decision:
    """The engine's answer: one movie, or an explanation that nothing qualified.

    `candidate_count` and `band_size` are reported so the API can say how many options
    remain, and so a surprising pick can be investigated after the fact.
    """

    reason: DecisionReason
    movie: CandidateMovie | None
    breakdown: ScoreBreakdown | None
    highlights: tuple[Highlight, ...]
    candidate_count: int
    band_size: int

    @property
    def found(self) -> bool:
        """True when a movie was returned."""
        return self.movie is not None
