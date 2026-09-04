"""Failure modes of the TMDb API, separated by what the caller should do about them."""


class TMDbError(Exception):
    """Base class. Catching this catches everything the client can raise."""


class TMDbAuthError(TMDbError):
    """The token is missing, wrong, or revoked. Retrying will not help."""


class TMDbRequestError(TMDbError):
    """TMDb rejected the request (4xx). A bug on our side — do not retry."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(f"TMDb rejected the request ({status_code}): {message}")
        self.status_code = status_code
        self.message = message


class TMDbUnavailable(TMDbError):
    """Timeouts, transport failures, 5xx, or rate limiting that outlived our retries.

    Distinct from TMDbRequestError because the caller can reasonably fall back to
    cached data instead of failing the user's request.
    """
