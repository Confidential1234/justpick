"""Parsing, against real recorded payloads and against the malformed ones TMDb also sends."""

from datetime import date

from app.tmdb.mappers import (
    parse_discover_page,
    parse_genre,
    parse_movie_details,
    parse_provider,
    to_candidate,
)

from .conftest import load


class TestDiscover:
    def test_parses_a_real_page(self) -> None:
        page = parse_discover_page(load("discover_page"))
        assert page.page == 1
        assert page.total_results > 0
        assert len(page.movies) == 5
        first = page.movies[0]
        assert first.tmdb_id > 0
        assert first.title
        assert isinstance(first.genre_ids, frozenset)

    def test_discover_results_carry_no_runtime(self) -> None:
        """The reason the engine has to tolerate a missing runtime at all."""
        raw = load("discover_page")
        assert all("runtime" not in movie for movie in raw["results"])

    def test_tolerates_a_row_with_almost_nothing_in_it(self) -> None:
        sparse = parse_discover_page({"results": [{"id": 42}]})
        movie = sparse.movies[0]
        assert movie.tmdb_id == 42
        assert movie.title == ""
        assert movie.genre_ids == frozenset()
        assert movie.release_date is None
        assert movie.vote_average == 0.0

    def test_falls_back_to_the_original_title(self) -> None:
        page = parse_discover_page({"results": [{"id": 1, "original_title": "Le Samouraï"}]})
        assert page.movies[0].title == "Le Samouraï"

    def test_empty_release_date_string_is_not_a_date(self) -> None:
        """TMDb sends "" for unreleased and unknown films, not null."""
        page = parse_discover_page({"results": [{"id": 1, "release_date": ""}]})
        assert page.movies[0].release_date is None

    def test_malformed_release_date_does_not_raise(self) -> None:
        page = parse_discover_page({"results": [{"id": 1, "release_date": "2015-13-45"}]})
        assert page.movies[0].release_date is None

    def test_missing_results_key_yields_an_empty_page(self) -> None:
        assert parse_discover_page({}).movies == ()


class TestMovieDetails:
    def test_parses_a_real_payload(self) -> None:
        details = parse_movie_details(load("movie_details"))
        assert details.tmdb_id > 0
        assert details.title
        assert details.runtime_minutes is not None and details.runtime_minutes > 0
        assert isinstance(details.release_date, date)
        assert details.genre_ids

    def test_extracts_us_flatrate_providers(self) -> None:
        details = parse_movie_details(load("movie_details"))
        assert details.flatrate_providers
        assert all(p.id > 0 and p.name for p in details.flatrate_providers)
        assert details.provider_ids == frozenset(p.id for p in details.flatrate_providers)

    def test_rent_and_buy_are_ignored(self) -> None:
        """Paying again is not "already available on your subscription"."""
        payload = {
            "id": 1,
            "watch/providers": {
                "results": {
                    "US": {
                        "flatrate": [{"provider_id": 8, "provider_name": "Netflix"}],
                        "rent": [{"provider_id": 2, "provider_name": "Apple TV"}],
                        "buy": [{"provider_id": 3, "provider_name": "Google Play"}],
                    }
                }
            },
        }
        assert parse_movie_details(payload).provider_ids == frozenset({8})

    def test_a_region_with_no_availability_is_empty_not_an_error(self) -> None:
        payload = {"id": 1, "watch/providers": {"results": {"GB": {"flatrate": []}}}}
        assert parse_movie_details(payload, region="US").flatrate_providers == ()

    def test_missing_providers_block_entirely(self) -> None:
        assert parse_movie_details({"id": 1}).flatrate_providers == ()

    def test_zero_runtime_is_treated_as_unknown(self) -> None:
        """TMDb uses 0 for "we don't know", which is not a 0-minute film."""
        assert parse_movie_details({"id": 1, "runtime": 0}).runtime_minutes is None


class TestGenresAndProviders:
    def test_parses_the_real_genre_list(self) -> None:
        genres = [parse_genre(g) for g in load("genres")["genres"]]
        assert len(genres) == 19
        assert {g.name for g in genres} >= {"Action", "Comedy", "Science Fiction"}

    def test_finds_netflix_and_prime_in_the_real_provider_list(self) -> None:
        providers = [parse_provider(p) for p in load("watch_providers_us")["results"]]
        by_id = {p.id: p.name for p in providers}
        assert by_id[8] == "Netflix"
        assert by_id[9] == "Amazon Prime Video"


class TestToCandidate:
    def test_carries_the_requested_providers_through(self) -> None:
        """Discover already guaranteed availability; it just does not say on which service."""
        movie = parse_discover_page(load("discover_page")).movies[0]
        candidate = to_candidate(movie, frozenset({8, 9}))
        assert candidate.provider_ids == frozenset({8, 9})

    def test_runtime_is_unknown_unless_supplied(self) -> None:
        movie = parse_discover_page(load("discover_page")).movies[0]
        assert to_candidate(movie, frozenset({8})).runtime_minutes is None
        assert to_candidate(movie, frozenset({8}), runtime_minutes=97).runtime_minutes == 97

    def test_preserves_the_fields_the_engine_scores_on(self) -> None:
        movie = parse_discover_page(load("discover_page")).movies[0]
        candidate = to_candidate(movie, frozenset({8}))
        assert candidate.tmdb_id == movie.tmdb_id
        assert candidate.title == movie.title
        assert candidate.genre_ids == movie.genre_ids
        assert candidate.vote_average == movie.vote_average
        assert candidate.vote_count == movie.vote_count
        assert candidate.release_date == movie.release_date
