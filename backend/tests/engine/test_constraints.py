"""Hard constraints: what gets a movie eliminated, and — just as importantly — what does not."""

from datetime import date

import pytest

from app.engine.constraints import (
    MIN_VOTE_COUNT,
    counts_if_relaxed,
    failures,
    survivors,
)
from app.engine.models import Constraint

from .conftest import ACTION, COMEDY, PRIME, SCIFI, movie, request

NO_EXCLUSIONS: frozenset[int] = frozenset()


def test_a_default_movie_passes_everything(today: date) -> None:
    assert failures(movie(), request(), NO_EXCLUSIONS, today) == frozenset()


@pytest.mark.parametrize(
    ("constraint", "overrides"),
    [
        (Constraint.PROVIDER, {"provider_ids": frozenset({999})}),
        (Constraint.RUNTIME, {"runtime_minutes": 121}),
        (Constraint.VOTE_COUNT, {"vote_count": MIN_VOTE_COUNT - 1}),
        (Constraint.GENRE, {"genre_ids": frozenset({COMEDY})}),
        (Constraint.RELEASED, {"release_date": None}),
        (Constraint.RELEASED, {"release_date": date(2030, 1, 1)}),
        (Constraint.ADULT, {"adult": True}),
    ],
)
def test_each_constraint_eliminates_and_only_it(
    constraint: Constraint, overrides: dict[str, object], today: date
) -> None:
    """One broken field should produce exactly one failure, not a cascade."""
    assert failures(movie(**overrides), request(), NO_EXCLUSIONS, today) == frozenset({constraint})


def test_rating_floor_eliminates_only_when_requested(today: date) -> None:
    dim = movie(vote_average=6.0)
    assert failures(dim, request(), NO_EXCLUSIONS, today) == frozenset()
    assert failures(dim, request(min_rating=7.0), NO_EXCLUSIONS, today) == frozenset(
        {Constraint.RATING}
    )


def test_rating_floor_is_inclusive(today: date) -> None:
    exact = movie(vote_average=7.0)
    assert failures(exact, request(min_rating=7.0), NO_EXCLUSIONS, today) == frozenset()


def test_runtime_limit_is_inclusive(today: date) -> None:
    exact = movie(runtime_minutes=120)
    assert failures(exact, request(max_runtime=120), NO_EXCLUSIONS, today) == frozenset()


def test_unknown_runtime_is_not_a_failure(today: date) -> None:
    """TMDb's discover filter already applied the limit; dropping these loses good films."""
    assert failures(movie(runtime_minutes=None), request(), NO_EXCLUSIONS, today) == frozenset()


def test_released_today_is_allowed(today: date) -> None:
    assert failures(movie(release_date=today), request(), NO_EXCLUSIONS, today) == frozenset()


def test_no_genre_preference_means_anything_not_nothing(today: date) -> None:
    obscure_genre = movie(genre_ids=frozenset({12345}))
    any_genre = request(genre_ids=frozenset())
    assert failures(obscure_genre, any_genre, NO_EXCLUSIONS, today) == frozenset()


def test_partial_genre_overlap_is_enough(today: date) -> None:
    action_only = movie(genre_ids=frozenset({ACTION}))
    both_requested = request(genre_ids=frozenset({ACTION, SCIFI}))
    assert failures(action_only, both_requested, NO_EXCLUSIONS, today) == frozenset()


def test_any_provider_overlap_is_enough(today: date) -> None:
    prime_only = movie(provider_ids=frozenset({PRIME}))
    assert failures(prime_only, request(), NO_EXCLUSIONS, today) == frozenset()


def test_excluded_movies_fail(today: date) -> None:
    rejected = movie()
    assert failures(rejected, request(), frozenset({rejected.tmdb_id}), today) == frozenset(
        {Constraint.EXCLUDED}
    )


def test_failures_reports_every_problem_not_just_the_first(today: date) -> None:
    broken = movie(runtime_minutes=200, vote_count=3, adult=True)
    assert failures(broken, request(), NO_EXCLUSIONS, today) == frozenset(
        {Constraint.RUNTIME, Constraint.VOTE_COUNT, Constraint.ADULT}
    )


def test_survivors_keeps_only_the_eligible(today: date) -> None:
    good, bad = movie(), movie(runtime_minutes=300)
    assert survivors([good, bad], request(), NO_EXCLUSIONS, today) == [good]


class TestRelaxationCounts:
    """Powers the "Try 2h30m instead (23 movies)" affordance on an empty result."""

    def test_counts_movies_blocked_by_exactly_one_constraint(self, today: date) -> None:
        candidates = [
            movie(runtime_minutes=140),
            movie(runtime_minutes=150),
            movie(genre_ids=frozenset({COMEDY})),
        ]
        counts = counts_if_relaxed(candidates, request(), NO_EXCLUSIONS, today)
        assert counts[Constraint.RUNTIME] == 2
        assert counts[Constraint.GENRE] == 1

    def test_ignores_movies_with_more_than_one_problem(self, today: date) -> None:
        """Relaxing runtime would not surface a film that is also the wrong genre."""
        candidates = [movie(runtime_minutes=140, genre_ids=frozenset({COMEDY}))]
        counts = counts_if_relaxed(candidates, request(), NO_EXCLUSIONS, today)
        assert counts[Constraint.RUNTIME] == 0
        assert counts[Constraint.GENRE] == 0

    def test_never_offers_to_relax_our_own_quality_rules(self, today: date) -> None:
        candidates = [movie(vote_count=2), movie(adult=True)]
        counts = counts_if_relaxed(candidates, request(), NO_EXCLUSIONS, today)
        assert Constraint.VOTE_COUNT not in counts
        assert Constraint.ADULT not in counts
        assert Constraint.EXCLUDED not in counts

    def test_eligible_movies_do_not_count_toward_any_relaxation(self, today: date) -> None:
        counts = counts_if_relaxed([movie(), movie()], request(), NO_EXCLUSIONS, today)
        assert set(counts.values()) == {0}
