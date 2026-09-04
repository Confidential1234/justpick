"""Scoring: the weights are product judgement, so these tests are where that judgement is stated."""

import random

import pytest

from app.engine.scoring import (
    CONFIDENCE_SATURATION,
    WEIGHTS,
    confidence,
    genre_match,
    highlights,
    rating,
    runtime_fit,
    score,
)

from .conftest import ACTION, COMEDY, SCIFI, movie, request


def test_weights_sum_to_one() -> None:
    assert sum(WEIGHTS.values()) == pytest.approx(1.0)


def test_genre_match_is_the_heaviest_component() -> None:
    """It is the only input that states intent; the rest proxy quality."""
    assert max(WEIGHTS, key=lambda k: WEIGHTS[k]) == "genre_match"


def test_there_is_no_recency_component() -> None:
    """An older film you have not seen is not a worse answer than a new one you have not seen."""
    assert "recency" not in WEIGHTS


class TestGenreMatch:
    def test_full_overlap_scores_one(self) -> None:
        both = movie(genre_ids=frozenset({ACTION, SCIFI}))
        assert genre_match(both, request(genre_ids=frozenset({ACTION, SCIFI}))) == 1.0

    def test_half_overlap_scores_half(self) -> None:
        one = movie(genre_ids=frozenset({ACTION}))
        assert genre_match(one, request(genre_ids=frozenset({ACTION, SCIFI}))) == 0.5

    def test_extra_genres_on_the_movie_do_not_dilute_it(self) -> None:
        """Asked for Action; a film that is Action plus four other things still fully matches."""
        busy = movie(genre_ids=frozenset({ACTION, SCIFI, COMEDY, 18, 12}))
        assert genre_match(busy, request(genre_ids=frozenset({ACTION}))) == 1.0

    def test_no_preference_is_neutral_not_zero(self) -> None:
        assert genre_match(movie(), request(genre_ids=frozenset())) == 0.5


class TestRating:
    def test_normalises_over_the_range_ratings_actually_occupy(self) -> None:
        assert rating(movie(vote_average=5.0)) == 0.0
        assert rating(movie(vote_average=7.0)) == pytest.approx(0.5)
        assert rating(movie(vote_average=9.0)) == 1.0

    def test_clamps_outside_the_range(self) -> None:
        assert rating(movie(vote_average=2.0)) == 0.0
        assert rating(movie(vote_average=10.0)) == 1.0


class TestConfidence:
    def test_saturates_so_blockbusters_do_not_run_away_with_it(self) -> None:
        assert confidence(movie(vote_count=CONFIDENCE_SATURATION)) == pytest.approx(1.0)
        assert confidence(movie(vote_count=CONFIDENCE_SATURATION * 50)) == pytest.approx(1.0)

    def test_more_votes_never_hurts(self) -> None:
        counts = [100, 500, 1_000, 5_000, 20_000]
        scores = [confidence(movie(vote_count=c)) for c in counts]
        assert scores == sorted(scores)

    def test_zero_votes_is_handled(self) -> None:
        assert confidence(movie(vote_count=0)) == 0.0


class TestRuntimeFit:
    def test_rewards_using_the_time_budget(self) -> None:
        """"Under two hours" means "I have two hours", not "give me the shortest thing"."""
        long_enough = runtime_fit(movie(runtime_minutes=115), request(max_runtime=120))
        too_short = runtime_fit(movie(runtime_minutes=45), request(max_runtime=120))
        assert long_enough > too_short

    def test_exactly_at_the_limit_is_a_perfect_fit(self) -> None:
        assert runtime_fit(movie(runtime_minutes=120), request(max_runtime=120)) == 1.0

    def test_unknown_runtime_is_neutral(self) -> None:
        assert runtime_fit(movie(runtime_minutes=None), request()) == 0.5

    def test_nonsense_budget_does_not_explode(self) -> None:
        assert runtime_fit(movie(), request(max_runtime=0)) == 0.5


class TestScore:
    def test_a_perfect_movie_scores_one(self) -> None:
        perfect = movie(
            genre_ids=frozenset({ACTION}),
            vote_average=9.0,
            vote_count=CONFIDENCE_SATURATION,
            runtime_minutes=120,
        )
        assert score(perfect, request(max_runtime=120)).total == pytest.approx(1.0)

    def test_total_is_the_weighted_sum_of_its_parts(self) -> None:
        breakdown = score(movie(), request())
        expected = sum(WEIGHTS[name] * getattr(breakdown, name) for name in WEIGHTS)
        assert breakdown.total == pytest.approx(expected)

    def test_every_component_stays_in_range_on_fuzzed_input(self) -> None:
        rng = random.Random(20260904)
        for _ in range(500):
            candidate = movie(
                genre_ids=frozenset(rng.sample(range(1, 40), rng.randint(0, 5))),
                vote_average=rng.uniform(-5, 15),
                vote_count=rng.randint(0, 500_000),
                runtime_minutes=rng.choice([None, rng.randint(1, 400)]),
            )
            req = request(
                genre_ids=frozenset(rng.sample(range(1, 40), rng.randint(0, 3))),
                max_runtime=rng.randint(0, 400),
            )
            breakdown = score(candidate, req)
            for name in WEIGHTS:
                assert 0.0 <= getattr(breakdown, name) <= 1.0, name
            assert 0.0 <= breakdown.total <= 1.0


class TestHighlights:
    def test_returns_the_largest_weighted_contributors_first(self) -> None:
        breakdown = score(movie(), request())
        result = highlights(breakdown)
        assert len(result) == 2
        assert result[0].contribution >= result[1].contribution

    def test_ranks_by_weighted_contribution_not_raw_subscore(self) -> None:
        """A perfect runtime_fit at 0.15 should not outrank a decent genre_match at 0.40."""
        candidate = movie(genre_ids=frozenset({ACTION}), runtime_minutes=120)
        top = highlights(score(candidate, request(max_runtime=120)))[0]
        assert top.component == "genre_match"

    def test_is_deterministic_when_contributions_tie(self) -> None:
        breakdown = score(movie(), request())
        assert highlights(breakdown) == highlights(breakdown)
