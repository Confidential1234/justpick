"""Turning service values into wire values, including the human-readable bits.

The engine deals in genre *ids* and weighted contributions; the reasons a person reads
are assembled here, where genre names are available.
"""

from app.api.schemas import (
    GenreOut,
    HighlightOut,
    MovieOut,
    ProviderOut,
    RelaxationHint,
)
from app.engine.models import Constraint, Highlight
from app.services.views import MovieView

_COMPONENT_LABELS = {
    "genre_match": "Matches what you're in the mood for",
    "rating": "Well reviewed",
    "runtime_fit": "Fits the time you have",
}

# field name the client sent -> how it can be loosened
_RELAXATION = {
    Constraint.RATING: ("min_rating", "remove", "Any rating"),
    Constraint.RUNTIME: ("max_runtime", "remove", "Any length"),
    Constraint.RELEASE_YEAR: ("min_year", "remove", "Any year"),
    Constraint.GENRE: ("genre_ids", "clear", "Any genre"),
    Constraint.PROVIDER: ("provider_ids", "add", "More services"),
}


def movie_out(view: MovieView) -> MovieOut:
    """Convert a service-layer view into the wire model."""
    return MovieOut(
        tmdb_id=view.tmdb_id,
        title=view.title,
        overview=view.overview,
        release_year=view.release_year,
        runtime_minutes=view.runtime_minutes,
        vote_average=view.vote_average,
        vote_count=view.vote_count,
        poster_url=view.poster_url,
        genres=[GenreOut(id=g.id, name=g.name) for g in view.genres],
        providers=[
            ProviderOut(id=p.id, name=p.name, logo_url=p.logo_url) for p in view.providers
        ],
        tmdb_url=view.tmdb_url,
    )


def why(
    view: MovieView,
    highlights: tuple[Highlight, ...],
    requested_genre_ids: frozenset[int] = frozenset(),
) -> list[str]:
    """Short reasons, specific where the data allows it.

    Genre reasons name only the genres the user actually asked for. RoboCop is tagged
    Action, Thriller and Science Fiction; saying "Matches Action, Thriller" to someone
    who asked for Action and Sci-Fi claims a match that was not part of the request.
    """
    matched = [g.name for g in view.genres if g.id in requested_genre_ids]
    reasons: list[str] = []
    for highlight in highlights:
        if highlight.component == "genre_match" and matched:
            reasons.append(f"Matches {', '.join(matched[:2])}")
        elif highlight.component == "genre_match" and view.genres:
            # No genre filter was set, so describe the film rather than claim a match.
            reasons.append(", ".join(g.name for g in view.genres[:2]))
        elif highlight.component == "rating":
            reasons.append(f"Rated {view.vote_average:.1f}")
        elif highlight.component == "runtime_fit" and view.runtime_minutes:
            reasons.append(f"{view.runtime_minutes} minutes")
        else:
            reasons.append(_COMPONENT_LABELS.get(highlight.component, highlight.component))
    return reasons


def highlights_out(highlights: tuple[Highlight, ...]) -> list[HighlightOut]:
    """Expose the score components that drove the pick, for debugging and transparency."""
    return [
        HighlightOut(component=h.component, contribution=round(h.contribution, 4))
        for h in highlights
    ]


def relaxation_hints(counts: dict[Constraint, int]) -> list[RelaxationHint]:
    """Only offer relaxations that would actually produce something."""
    hints = [
        RelaxationHint(
            field=_RELAXATION[constraint][0],
            action=_RELAXATION[constraint][1],
            label=_RELAXATION[constraint][2],
            would_yield=count,
        )
        for constraint, count in counts.items()
        if count > 0 and constraint in _RELAXATION
    ]
    hints.sort(key=lambda h: -h.would_yield)
    return hints
