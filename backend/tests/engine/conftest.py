"""Builders for engine tests.

Every field has a default that passes every hard constraint, so a test overrides only the
one thing it is actually about and a reader can see the point of the test at a glance.
"""

from datetime import date

import pytest

from app.engine.models import CandidateMovie, DecisionRequest

TODAY = date(2026, 9, 4)

NETFLIX = 8
PRIME = 9
ACTION = 28
SCIFI = 878
COMEDY = 35

_next_id = iter(range(1000, 100_000))


def movie(**overrides: object) -> CandidateMovie:
    defaults: dict[str, object] = {
        "tmdb_id": next(_next_id),
        "title": "Default Movie",
        "genre_ids": frozenset({ACTION}),
        "provider_ids": frozenset({NETFLIX}),
        "vote_average": 7.0,
        "vote_count": 5_000,
        "runtime_minutes": 110,
        "release_date": date(2015, 1, 1),
        "adult": False,
    }
    return CandidateMovie(**(defaults | overrides))  # type: ignore[arg-type]


def request(**overrides: object) -> DecisionRequest:
    defaults: dict[str, object] = {
        "provider_ids": frozenset({NETFLIX, PRIME}),
        "genre_ids": frozenset({ACTION}),
        "max_runtime": 120,
        "min_rating": None,
    }
    return DecisionRequest(**(defaults | overrides))  # type: ignore[arg-type]


@pytest.fixture
def today() -> date:
    return TODAY
