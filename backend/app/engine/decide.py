"""The decision itself: constraints, then scoring, then one movie.

Pure and deterministic. Same arguments in, same movie out, every time — including the
randomness, which is seeded by the caller rather than drawn from global state.
"""

import math
import random
from collections.abc import Sequence
from datetime import date

from app.engine.constraints import survivors
from app.engine.models import (
    CandidateMovie,
    Decision,
    DecisionReason,
    DecisionRequest,
    ScoredMovie,
)
from app.engine.scoring import highlights, score

# The pick is drawn from the top slice rather than always taking rank #1.
#
# Strict argmax has two failure modes. Rejecting the top result hands back rank #2, which
# is by construction the movie most similar to the one just rejected, so rejection feels
# inert; and every user with the same filters gets the same movie forever.
#
# The floor matters more than the fraction. Real requests are narrow — two genres, two
# hours and a 8+ rating filter leaves about fifteen candidates against the live TMDb
# catalogue, where a bare 10% band would be a single movie and collapse straight back
# into argmax.
BAND_FRACTION = 0.10
MIN_BAND = 5


def rank(
    candidates: Sequence[CandidateMovie],
    request: DecisionRequest,
    excluded_movie_ids: frozenset[int],
    today: date,
) -> list[ScoredMovie]:
    """Eligible candidates, best first. Ties break on lower tmdb_id.

    The tiebreak is not cosmetic: without it, band membership would depend on the input
    ordering, and equal-scoring movies would drift in and out of contention.
    """
    eligible = survivors(candidates, request, excluded_movie_ids, today)
    scored = [ScoredMovie(movie=m, breakdown=score(m, request)) for m in eligible]
    scored.sort(key=lambda s: (-s.breakdown.total, s.movie.tmdb_id))
    return scored


def band_size(candidate_count: int) -> int:
    """How many of the top-ranked candidates to draw from.

    Never larger than the pool, and never smaller than MIN_BAND unless there are
    genuinely fewer candidates than that.
    """
    if candidate_count <= 0:
        return 0
    return min(candidate_count, max(MIN_BAND, math.ceil(candidate_count * BAND_FRACTION)))


def decide(
    candidates: Sequence[CandidateMovie],
    request: DecisionRequest,
    excluded_movie_ids: frozenset[int],
    seed: str,
    today: date,
) -> Decision:
    """Return exactly one movie, or a Decision explaining that nothing qualified.

    `seed` should identify the attempt, e.g. f"{session_id}:{attempt}". Reusing a seed
    reproduces the pick; incrementing the attempt moves it somewhere else in the band.
    """
    ranked = rank(candidates, request, excluded_movie_ids, today)

    if not ranked:
        return Decision(
            reason=DecisionReason.NO_CANDIDATES,
            movie=None,
            breakdown=None,
            highlights=(),
            candidate_count=0,
            band_size=0,
        )

    size = band_size(len(ranked))
    chosen = random.Random(seed).choice(ranked[:size])

    return Decision(
        reason=DecisionReason.OK,
        movie=chosen.movie,
        breakdown=chosen.breakdown,
        highlights=highlights(chosen.breakdown),
        candidate_count=len(ranked),
        band_size=size,
    )
