"""Scoring: the weights are product judgement, so these tests are where that judgement is stated."""

import random

import pytest

from app.engine.scoring import (
    POOL_MEAN_RATING,
    RATING_PRIOR_VOTES,
    WEIGHTS,
    adjusted_rating,
    genre_match,
    highlights,
    rating,
    runtime_fit,
    score,
)

from .conftest import ACTION, COMEDY, SCIFI, movie, request

WELL_VOTED = 100_000  # enough that shrinkage is negligible


def test_weights_sum_to_one() -> None:
    assert sum(WEIGHTS.values()) == pytest.approx(1.0)


def test_intent_and_quality_dominate_over_fit() -> None:
    """Genre and rating decide; runtime only breaks near-ties.

    Rating carries slightly more nominal weight than genre, which looks backwards for an
    app built around stated intent — but the GENRE hard constraint has already thrown out
    everything that does not overlap, so genre_match is 1.0 for most survivors and only
    separates candidates when several genres were picked. Rating does the real ordering.
    """
    assert WEIGHTS["genre_match"] + WEIGHTS["rating"] >= 0.8
    assert min(WEIGHTS, key=lambda k: WEIGHTS[k]) == "runtime_fit"


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


class TestAdjustedRating:
    """A raw average is not comparable across sample sizes; this makes it so."""

    def test_the_case_that_prompted_this(self) -> None:
        """TMDb had this at 9.9 from 143 votes. IMDb had it at 5.6."""
        inflated = movie(vote_average=9.9, vote_count=143)
        assert adjusted_rating(inflated) == pytest.approx(7.48, abs=0.02)

    def test_a_heavily_voted_score_is_left_almost_untouched(self) -> None:
        acclaimed = movie(vote_average=8.4, vote_count=30_000)
        assert adjusted_rating(acclaimed) == pytest.approx(8.4, abs=0.05)

    def test_a_thin_sample_beats_nothing_and_loses_to_a_real_one(self) -> None:
        thin = movie(vote_average=9.5, vote_count=120)
        solid = movie(vote_average=8.2, vote_count=25_000)
        assert adjusted_rating(thin) < adjusted_rating(solid)

    def test_zero_votes_falls_back_to_the_pool_mean(self) -> None:
        assert adjusted_rating(movie(vote_count=0)) == pytest.approx(POOL_MEAN_RATING)

    def test_the_prior_carries_half_the_weight_at_the_prior_vote_count(self) -> None:
        halfway = movie(vote_average=9.13, vote_count=RATING_PRIOR_VOTES)
        assert adjusted_rating(halfway) == pytest.approx((9.13 + POOL_MEAN_RATING) / 2)

    def test_a_below_average_film_is_pulled_up_not_down(self) -> None:
        poor = movie(vote_average=4.0, vote_count=200)
        assert 4.0 < adjusted_rating(poor) < POOL_MEAN_RATING

    def test_more_votes_move_a_score_toward_its_own_average(self) -> None:
        gaps = [
            abs(adjusted_rating(movie(vote_average=9.0, vote_count=v)) - 9.0)
            for v in (100, 1_000, 10_000, 100_000)
        ]
        assert gaps == sorted(gaps, reverse=True)


class TestRating:
    def test_normalises_over_the_range_ratings_actually_occupy(self) -> None:
        assert rating(movie(vote_average=5.0, vote_count=WELL_VOTED)) == pytest.approx(
            0.0, abs=0.01
        )
        assert rating(movie(vote_average=7.0, vote_count=WELL_VOTED)) == pytest.approx(
            0.5, abs=0.01
        )
        assert rating(movie(vote_average=9.0, vote_count=WELL_VOTED)) == pytest.approx(
            1.0, abs=0.01
        )

    def test_clamps_outside_the_range(self) -> None:
        assert rating(movie(vote_average=2.0, vote_count=WELL_VOTED)) == 0.0
        assert rating(movie(vote_average=10.0, vote_count=WELL_VOTED)) == 1.0


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
            vote_average=9.5,
            vote_count=WELL_VOTED,
            runtime_minutes=120,
        )
        assert score(perfect, request(max_runtime=120)).total == pytest.approx(1.0)

    def test_an_inflated_score_loses_to_a_well_reviewed_one(self) -> None:
        """The whole point: 9.9 from 143 voters must not beat 8.4 from 30,000."""
        req = request(genre_ids=frozenset({ACTION}), max_runtime=120)
        inflated = movie(vote_average=9.9, vote_count=143, runtime_minutes=90)
        acclaimed = movie(vote_average=8.4, vote_count=30_000, runtime_minutes=115)
        assert score(inflated, req).total < score(acclaimed, req).total

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
