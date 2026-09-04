"""decide(): one movie out, reproducibly."""

from datetime import date

from app.engine.decide import MIN_BAND, band_size, decide, rank
from app.engine.models import DecisionReason

from .conftest import ACTION, COMEDY, SCIFI, movie, request

NO_EXCLUSIONS: frozenset[int] = frozenset()
SEED = "session-abc:1"


def _pool(n: int, **overrides: object) -> list:
    return [movie(**overrides) for _ in range(n)]


class TestEmptyAndDegenerate:
    def test_no_candidates_at_all(self, today: date) -> None:
        result = decide([], request(), NO_EXCLUSIONS, SEED, today)
        assert result.reason is DecisionReason.NO_CANDIDATES
        assert result.movie is None
        assert result.found is False
        assert result.candidate_count == 0

    def test_candidates_that_all_fail_constraints(self, today: date) -> None:
        result = decide(_pool(10, runtime_minutes=400), request(), NO_EXCLUSIONS, SEED, today)
        assert result.reason is DecisionReason.NO_CANDIDATES
        assert result.movie is None

    def test_a_single_eligible_movie_is_returned(self, today: date) -> None:
        only = movie()
        result = decide([only], request(), NO_EXCLUSIONS, SEED, today)
        assert result.movie == only
        assert result.candidate_count == 1
        assert result.band_size == 1


class TestDeterminism:
    def test_same_inputs_produce_the_same_movie_every_time(self, today: date) -> None:
        pool = _pool(200)
        picks = {
            decide(pool, request(), NO_EXCLUSIONS, SEED, today).movie for _ in range(100)
        }
        assert len(picks) == 1

    def test_input_ordering_does_not_change_the_result(self, today: date) -> None:
        pool = _pool(50)
        forwards = decide(pool, request(), NO_EXCLUSIONS, SEED, today)
        backwards = decide(list(reversed(pool)), request(), NO_EXCLUSIONS, SEED, today)
        assert forwards.movie == backwards.movie

    def test_ties_break_on_lower_tmdb_id(self, today: date) -> None:
        """Identical movies differing only by id must rank in a fixed order."""
        identical = [movie(tmdb_id=i, title=f"Clone {i}") for i in (500, 100, 300)]
        ranked = rank(identical, request(), NO_EXCLUSIONS, today)
        assert [s.movie.tmdb_id for s in ranked] == [100, 300, 500]

    def test_a_strictly_better_movie_always_ranks_first(self, today: date) -> None:
        best = movie(
            tmdb_id=99_999,  # highest id, so the tiebreak cannot be what puts it on top
            genre_ids=frozenset({ACTION, SCIFI}),
            vote_average=8.9,
            vote_count=90_000,
            runtime_minutes=119,
        )
        worse = _pool(30, vote_average=6.0, vote_count=200, runtime_minutes=70)
        req = request(genre_ids=frozenset({ACTION, SCIFI}), max_runtime=120)
        assert rank([*worse, best], req, NO_EXCLUSIONS, today)[0].movie == best


class TestBand:
    def test_band_never_collapses_to_a_single_movie(self) -> None:
        """A 10% band of 15 candidates would be 1, which is just argmax again."""
        assert band_size(15) == MIN_BAND
        assert band_size(3) == 3  # unless there are genuinely fewer than the floor

    def test_band_grows_with_the_pool(self) -> None:
        assert band_size(1000) == 100

    def test_band_is_never_larger_than_the_pool(self) -> None:
        for n in range(1, 60):
            assert band_size(n) <= n

    def test_empty_pool_has_no_band(self) -> None:
        assert band_size(0) == 0

    def test_the_pick_comes_from_inside_the_band(self, today: date) -> None:
        pool = _pool(100)
        req = request()
        for attempt in range(30):
            result = decide(pool, req, NO_EXCLUSIONS, f"s:{attempt}", today)
            ranked = rank(pool, req, NO_EXCLUSIONS, today)[: result.band_size]
            top = {s.movie.tmdb_id for s in ranked}
            assert result.movie is not None
            assert result.movie.tmdb_id in top


class TestVariety:
    def test_different_attempts_move_around_the_band(self, today: date) -> None:
        """Rejection has to feel like it did something, not hand back the next rank down."""
        pool = _pool(200)
        picks = {
            decide(pool, request(), NO_EXCLUSIONS, f"session-abc:{n}", today).movie
            for n in range(20)
        }
        assert len(picks) > 1

    def test_different_sessions_are_not_all_given_the_same_movie(self, today: date) -> None:
        pool = _pool(200)
        picks = {
            decide(pool, request(), NO_EXCLUSIONS, f"session-{n}:1", today).movie
            for n in range(20)
        }
        assert len(picks) > 1


class TestExclusions:
    def test_an_excluded_movie_is_never_returned(self, today: date) -> None:
        pool = _pool(40)
        # Exclude everything except one film, which must then be the only possible answer.
        survivor = pool[7]
        excluded = frozenset(m.tmdb_id for m in pool if m is not survivor)
        result = decide(pool, request(), excluded, SEED, today)
        assert result.movie == survivor

    def test_rejecting_the_whole_pool_exhausts_it(self, today: date) -> None:
        pool = _pool(8)
        excluded = frozenset(m.tmdb_id for m in pool)
        assert decide(pool, request(), excluded, SEED, today).reason is DecisionReason.NO_CANDIDATES

    def test_repeated_rejection_never_repeats_a_movie(self, today: date) -> None:
        """Walk the full accept/reject loop the way the API will."""
        pool = _pool(30)
        seen: set[int] = set()
        for attempt in range(1, 31):
            result = decide(pool, request(), frozenset(seen), f"s:{attempt}", today)
            assert result.movie is not None, f"exhausted early at attempt {attempt}"
            assert result.movie.tmdb_id not in seen
            seen.add(result.movie.tmdb_id)
        assert len(seen) == 30
        assert decide(pool, request(), frozenset(seen), "s:31", today).found is False


class TestReportedCounts:
    def test_candidate_count_reflects_eligibility_not_input_size(self, today: date) -> None:
        pool = [*_pool(5), *_pool(20, genre_ids=frozenset({COMEDY}))]
        result = decide(pool, request(genre_ids=frozenset({ACTION})), NO_EXCLUSIONS, SEED, today)
        assert result.candidate_count == 5

    def test_a_successful_decision_explains_itself(self, today: date) -> None:
        result = decide(_pool(20), request(), NO_EXCLUSIONS, SEED, today)
        assert result.breakdown is not None
        assert len(result.highlights) == 2
        assert all(h.contribution > 0 for h in result.highlights)
