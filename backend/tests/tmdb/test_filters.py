"""Discover query construction.

Small surface, high stakes: these params are the difference between the engine seeing
1,410 candidates and seeing 196, and getting them wrong fails silently.
"""

from app.tmdb.client import NETFLIX, PRIME_VIDEO, DiscoverFilters

BOTH = frozenset({NETFLIX, PRIME_VIDEO})
ACTION, SCIFI = 28, 878


def test_providers_are_joined_with_a_pipe() -> None:
    assert DiscoverFilters(provider_ids=BOTH).as_params()["with_watch_providers"] == "8|9"


def test_genres_are_ored_not_anded() -> None:
    """Comma means AND at TMDb. "Action or Sci-Fi" is 1,410 results; "and" is 196."""
    params = DiscoverFilters(provider_ids=BOTH, genre_ids=frozenset({ACTION, SCIFI})).as_params()
    assert params["with_genres"] == "28|878"
    assert "," not in params["with_genres"]


def test_ids_are_ordered_so_the_same_request_produces_the_same_url() -> None:
    """Sets iterate arbitrarily; unordered params would defeat any response caching."""
    a = DiscoverFilters(provider_ids=BOTH, genre_ids=frozenset({SCIFI, ACTION})).as_params()
    b = DiscoverFilters(provider_ids=BOTH, genre_ids=frozenset({ACTION, SCIFI})).as_params()
    assert a == b


def test_only_subscription_titles_are_requested() -> None:
    """Rent and buy are not "available on your services" in any useful sense."""
    params = DiscoverFilters(provider_ids=BOTH).as_params()
    assert params["with_watch_monetization_types"] == "flatrate"


def test_region_and_adult_defaults() -> None:
    params = DiscoverFilters(provider_ids=BOTH).as_params()
    assert params["watch_region"] == "US"
    assert params["include_adult"] == "false"


def test_optional_filters_are_omitted_when_unset() -> None:
    params = DiscoverFilters(provider_ids=BOTH).as_params()
    assert "with_genres" not in params
    assert "with_runtime.lte" not in params
    assert "vote_average.gte" not in params


def test_optional_filters_are_sent_when_set() -> None:
    params = DiscoverFilters(
        provider_ids=BOTH, max_runtime=120, min_rating=7.5
    ).as_params()
    assert params["with_runtime.lte"] == "120"
    assert params["vote_average.gte"] == "7.5"


def test_vote_count_floor_is_applied_by_default() -> None:
    assert DiscoverFilters(provider_ids=BOTH).as_params()["vote_count.gte"] == "100"


def test_a_zero_vote_floor_is_omitted_rather_than_sent() -> None:
    """TMDb answers 400 to vote_count.gte=0 — verified against the live API."""
    params = DiscoverFilters(provider_ids=BOTH, min_vote_count=0).as_params()
    assert "vote_count.gte" not in params
