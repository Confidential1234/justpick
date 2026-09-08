"""Scoring: ranks the movies that survived the hard constraints.

Every component returns a value in [0, 1] and is combined by a fixed weighted sum. The
weights are product judgement, not tuning output — they live in one dict so changing the
app's taste is a one-line diff with a test that fails if the weights stop summing to 1.
"""

from app.engine.models import CandidateMovie, DecisionRequest, Highlight, ScoreBreakdown

WEIGHTS: dict[str, float] = {
    # The only input that is a direct statement of intent; everything else proxies quality.
    "genre_match": 0.40,
    "rating": 0.45,
    "runtime_fit": 0.15,
}

# TMDb ratings cluster between roughly 5.5 and 8. Normalising over the raw 0-10 range would
# squash every meaningful difference into a tenth of a point.
RATING_FLOOR = 5.0
RATING_CEILING = 9.0

# Mean rating across the US Netflix/Prime catalogue, measured from a 200-film sample.
# Thinly-voted films are pulled toward this.
POOL_MEAN_RATING = 7.13

# Votes at which a film's own average carries half the weight against the pool mean.
# The median film in the catalogue has ~3,700 votes and the bottom decile ~560, so a
# thousand is roughly "enough people have seen this to believe the number".
RATING_PRIOR_VOTES = 1_000


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


def adjusted_rating(movie: CandidateMovie) -> float:
    """The film's rating, shrunk toward the pool mean in proportion to how few votes back it.

    A raw average is not comparable across sample sizes. TMDb had "The Way to the Heart"
    at 9.9 from 143 votes while IMDb had it at 5.6 from a similar number — a number that
    high on a sample that small is noise, or worse. This is the standard weighted-rating
    correction: it costs a 30,000-vote 8.4 almost nothing (8.36) and takes that 9.9 down
    to 7.48.

    A minimum-votes cutoff was the first attempt and it does not work — any threshold is
    arbitrary, and a film one vote above it is treated as fully trustworthy.
    """
    votes = max(movie.vote_count, 0)
    total = votes + RATING_PRIOR_VOTES
    return (votes * movie.vote_average + RATING_PRIOR_VOTES * POOL_MEAN_RATING) / total


def rating(movie: CandidateMovie) -> float:
    return _clamp((adjusted_rating(movie) - RATING_FLOOR) / (RATING_CEILING - RATING_FLOOR))


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
