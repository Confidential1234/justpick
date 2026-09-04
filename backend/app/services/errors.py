"""Service-level failures, named for what went wrong rather than for an HTTP status.

The API layer decides what each becomes on the wire.
"""


class ServiceError(Exception):
    pass


class RequestNotFound(ServiceError):
    """No such decision request, or it belongs to a different session."""


class RecommendationMismatch(ServiceError):
    """The recommendation exists but does not belong to this request."""


class AlreadyDecided(ServiceError):
    """This recommendation has already been accepted or rejected.

    Not an error the user caused — a double-tap or a retried request will do it — so the
    API answers 409 rather than pretending the second verdict counted.
    """


class UpstreamUnavailable(ServiceError):
    """The movie source is down, slow, or rate limiting us. Retrying may work."""


class UpstreamFailure(ServiceError):
    """The movie source rejected us: bad credentials or a malformed query. Our bug."""
