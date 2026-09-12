"""Hard constraints: requirements a movie must satisfy to be eligible at all.

These are separate from scoring on purpose. Scoring answers "which of these is best";
constraints answer "which of these are allowed", and a movie that fails one is never
returned no matter how well it would have scored.

`failures()` reports *every* constraint a movie fails rather than short-circuiting on the
first. That costs nothing and buys the relaxation hints: a candidate whose only failure is
RUNTIME is exactly a candidate the user would get back by allowing a longer film.
"""

from collections.abc import Iterable, Sequence
from datetime import date

from app.engine.models import CandidateMovie, Constraint, DecisionRequest

# Drops films nobody has rated at all. Deliberately low: with no rating floor set, the
# user has made no claim about quality, so neither should we.
MIN_VOTE_COUNT = 100

# Applied instead when the user *does* set a rating floor. Asking for "8+" is a claim
# about quality and deserves evidence behind it — a 9.9 from 143 voters is not a 9.9.
# Chosen rather than derived: it clears the thin-sample cases with margin while sitting
# below the bottom decile of popular films (~559 votes), so it stays permissive.
RATED_MIN_VOTE_COUNT = 300


def failures(
    movie: CandidateMovie,
    request: DecisionRequest,
    excluded_movie_ids: frozenset[int],
    today: date,
) -> frozenset[Constraint]:
    """Every hard constraint this movie fails. Empty means eligible."""
    failed: set[Constraint] = set()

    if not (movie.provider_ids & request.provider_ids):
        failed.add(Constraint.PROVIDER)

    # Unknown runtime is not a failure: TMDb's discover filter already applied the limit
    # upstream, and eliminating everything it did not return a runtime for would throw
    # away good candidates. It scores as a neutral fit instead.
    if movie.runtime_minutes is not None and movie.runtime_minutes > request.max_runtime:
        failed.add(Constraint.RUNTIME)

    # Compared against the raw score, because that is the number the user is choosing
    # from — picking "8+" should mean what TMDb displays. Reliability is a separate
    # question, answered by the vote floor below rather than by quietly adjusting the
    # figure the user asked about.
    #
    # The shrunk rating still decides *ordering* in scoring.py. Splitting the two is the
    # point: a statistic can be right for ranking and wrong for filtering.
    if request.min_rating is not None and movie.vote_average < request.min_rating:
        failed.add(Constraint.RATING)

    required_votes = MIN_VOTE_COUNT if request.min_rating is None else RATED_MIN_VOTE_COUNT
    if movie.vote_count < required_votes:
        failed.add(Constraint.VOTE_COUNT)

    # No genres selected means "anything", not "nothing".
    if request.genre_ids and not (movie.genre_ids & request.genre_ids):
        failed.add(Constraint.GENRE)

    if movie.tmdb_id in excluded_movie_ids:
        failed.add(Constraint.EXCLUDED)

    if movie.release_date is None or movie.release_date > today:
        failed.add(Constraint.RELEASED)
    elif request.min_year is not None and movie.release_date.year < request.min_year:
        # elif, so an undated film reports one problem rather than two — the relaxation
        # counts only look at candidates blocked by exactly one thing.
        failed.add(Constraint.RELEASE_YEAR)

    if movie.adult:
        failed.add(Constraint.ADULT)

    return frozenset(failed)


def survivors(
    candidates: Iterable[CandidateMovie],
    request: DecisionRequest,
    excluded_movie_ids: frozenset[int],
    today: date,
) -> list[CandidateMovie]:
    """The candidates that fail no hard constraint, in the order given."""
    return [m for m in candidates if not failures(m, request, excluded_movie_ids, today)]


# Constraints the user can actually loosen in the UI. ADULT, EXCLUDED, VOTE_COUNT and
# RELEASED are ours, not theirs, so offering to relax them would be nonsense.
RELAXABLE = (
    Constraint.RUNTIME,
    Constraint.RATING,
    Constraint.GENRE,
    Constraint.PROVIDER,
    Constraint.RELEASE_YEAR,
)


def counts_if_relaxed(
    candidates: Sequence[CandidateMovie],
    request: DecisionRequest,
    excluded_movie_ids: frozenset[int],
    today: date,
) -> dict[Constraint, int]:
    """How many more candidates each single relaxation would unlock.

    A movie counts toward relaxing X when X is the *only* thing wrong with it. Dropping a
    constraint that still leaves other failures would not actually surface the movie, so
    counting it would promise the user results they will not get.
    """
    unlocked = dict.fromkeys(RELAXABLE, 0)
    for movie in candidates:
        failed = failures(movie, request, excluded_movie_ids, today)
        if len(failed) == 1:
            only = next(iter(failed))
            if only in unlocked:
                unlocked[only] += 1
    return unlocked
