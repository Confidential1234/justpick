"""Decision engine: pure functions over plain dataclasses.

Imports nothing but the standard library. `tests/test_layering.py` enforces that.
"""

from app.engine.decide import decide, rank
from app.engine.models import (
    CandidateMovie,
    Constraint,
    Decision,
    DecisionReason,
    DecisionRequest,
    Highlight,
    ScoreBreakdown,
    ScoredMovie,
)

__all__ = [
    "CandidateMovie",
    "Constraint",
    "Decision",
    "DecisionReason",
    "DecisionRequest",
    "Highlight",
    "ScoreBreakdown",
    "ScoredMovie",
    "decide",
    "rank",
]
