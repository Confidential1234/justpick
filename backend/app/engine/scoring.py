"""Scoring: ranks the movies that survived the hard constraints.

Every component returns a value in [0, 1] and is combined by a fixed weighted sum. The
weights are product judgement, not tuning output — they live in one dict so changing the
app's taste is a one-line diff with a test that fails if the weights stop summing to 1.
"""

import math

from app.engine.models import CandidateMovie, DecisionRequest, Highlight, ScoreBreakdown

WEIGHTS: dict[str, float] = {
    # The only input that is a direct statement of intent; everything else proxies quality.
    "genre_match": 0.40,
    "rating": 0.30,
    # Guards `rating` — a 9.1 from 40 voters should not beat a 7.8 from 40,000.
    "confidence": 0.15,
    "runtime_fit": 0.15,
}

# TMDb ratings cluster between roughly 5.5 and 8. Normalising over the raw 0-10 range would
# squash every meaningful difference into a tenth of a point.
RATING_FLOOR = 5.0
RATING_CEILING = 9.0

# Past this many votes, more votes tell us nothing new.
CONFIDENCE_SATURATION = 10_000


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def genre_match(movie: CandidateMovie, request: DecisionRequest) -> float:
    """Fraction of the requested genres this movie satisfies.

    Overlap fraction rather than a boolean, which also generalises to more than one
    person's preferences: a genre both people picked scores 1.0, a one-sided pick partial.
    """
    if not request.genre_ids:
        return 0.5  # no preference stated - neutral, so other components decide
    return len(movie.genre_ids & request.genre_ids) / len(request.genre_ids)


def rating(movie: CandidateMovie) -> float:
    return _clamp((movie.vote_average - RATING_FLOOR) / (RATING_CEILING - RATING_FLOOR))


def confidence(movie: CandidateMovie) -> float:
    if movie.vote_count <= 0:
        return 0.0
    capped = min(movie.vote_count, CONFIDENCE_SATURATION)
    return _clamp(math.log10(capped) / math.log10(CONFIDENCE_SATURATION))


def runtime_fit(movie: CandidateMovie, request: DecisionRequest) -> float:
    """Rewards using the time budget rather than minimising runtime.

    "Under two hours" means "I have two hours", not "give me the shortest thing you have";
    a 40-minute film satisfies the constraint and misses the point.
    """
    if movie.runtime_minutes is None or request.max_runtime <= 0:
        return 0.5
    return _clamp(1.0 - (request.max_runtime - movie.runtime_minutes) / request.max_runtime)


def score(movie: CandidateMovie, request: DecisionRequest) -> ScoreBreakdown:
    components = {
        "genre_match": genre_match(movie, request),
        "rating": rating(movie),
        "confidence": confidence(movie),
        "runtime_fit": runtime_fit(movie, request),
    }
    total = sum(WEIGHTS[name] * value for name, value in components.items())
    return ScoreBreakdown(total=total, **components)


def highlights(breakdown: ScoreBreakdown, limit: int = 2) -> tuple[Highlight, ...]:
    """The components that contributed most to the total, largest first.

    Weighted contribution, not raw sub-score: a perfect `runtime_fit` at 0.15 matters less
    than a middling `genre_match` at 0.40, and the explanation should say so.
    """
    contributions = [
        Highlight(component=name, contribution=WEIGHTS[name] * getattr(breakdown, name))
        for name in WEIGHTS
    ]
    contributions.sort(key=lambda h: (-h.contribution, h.component))
    return tuple(contributions[:limit])
