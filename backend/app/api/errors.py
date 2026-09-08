"""Exception handlers: one JSON error shape for the whole API."""

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.api.schemas import ErrorOut, RelaxationHint
from app.services.errors import (
    AlreadyDecided,
    RecommendationMismatch,
    RequestNotFound,
    UpstreamFailure,
    UpstreamUnavailable,
)


class NoCandidates(Exception):
    """Nothing satisfies the constraints. Carries what the user could loosen."""

    def __init__(self, hints: list[RelaxationHint]) -> None:
        super().__init__("no candidates")
        self.hints = hints


def _error(status_code: int, error: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error": error, "message": message})


def register(app: FastAPI) -> None:
    """Attach every exception handler, so all errors share one flat JSON shape.

    Handlers live here rather than in the routes so that a client only ever has to parse
    one error format, whatever went wrong.
    """
    @app.exception_handler(NoCandidates)
    async def _no_candidates(request: Request, exc: NoCandidates) -> JSONResponse:
        # Raised rather than returned so it goes through the same handler pipeline as
        # every other error and comes out in the same flat shape.
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content=ErrorOut(
                error="no_candidates",
                message="No movies match those constraints.",
                relaxation_hints=exc.hints,
            ).model_dump(),
        )

    @app.exception_handler(RequestNotFound)
    async def _not_found(request: Request, exc: RequestNotFound) -> JSONResponse:
        return _error(status.HTTP_404_NOT_FOUND, "not_found", "No such decision.")

    @app.exception_handler(RecommendationMismatch)
    async def _mismatch(request: Request, exc: RecommendationMismatch) -> JSONResponse:
        return _error(
            status.HTTP_400_BAD_REQUEST,
            "recommendation_mismatch",
            "That recommendation does not belong to this decision.",
        )

    @app.exception_handler(AlreadyDecided)
    async def _already(request: Request, exc: AlreadyDecided) -> JSONResponse:
        return _error(
            status.HTTP_409_CONFLICT,
            "already_decided",
            "That recommendation has already been accepted or rejected.",
        )

    @app.exception_handler(UpstreamUnavailable)
    async def _upstream_down(request: Request, exc: UpstreamUnavailable) -> JSONResponse:
        return _error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "upstream_unavailable",
            "The movie database is not responding. Try again in a moment.",
        )

    @app.exception_handler(UpstreamFailure)
    async def _upstream_broken(request: Request, exc: UpstreamFailure) -> JSONResponse:
        # Bad credentials or a malformed query: our problem, not the caller's, so it must
        # never be reported as a 4xx.
        return _error(
            status.HTTP_502_BAD_GATEWAY,
            "upstream_failure",
            "Could not reach the movie database.",
        )
