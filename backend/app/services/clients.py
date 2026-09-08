"""Lifecycle for outbound clients.

Lives in the service layer rather than the API layer so routes never import app.tmdb
directly: they ask for a collaborator, they do not construct one.
"""

from app.config import get_settings
from app.tmdb.client import TMDbClient

__all__ = ["TMDbClient", "close_tmdb_client", "get_tmdb_client"]

_client: TMDbClient | None = None


def get_tmdb_client() -> TMDbClient:
    """The process-wide client. One connection pool, reused across requests."""
    global _client
    if _client is None:
        settings = get_settings()
        if not settings.tmdb_api_token:
            raise RuntimeError("TMDB_API_TOKEN is not configured")
        _client = TMDbClient(settings.tmdb_api_token, settings.tmdb_base_url)
    return _client


async def close_tmdb_client() -> None:
    """Release the connection pool. Called on application shutdown."""
    global _client
    if _client is not None:
        await _client.aclose()
    _client = None
