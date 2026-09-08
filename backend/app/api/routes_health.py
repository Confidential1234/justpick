"""Liveness endpoint.

Always returns 200 when the process is up. Database trouble is reported in the body
rather than as a 5xx, so a transient DB blip does not make the platform restart-loop
a perfectly healthy web process.
"""

from fastapi import APIRouter
from pydantic import BaseModel

from app import __version__
from app.config import get_settings
from app.db.session import DatabaseStatus, ping_database

router = APIRouter(tags=["meta"])


class HealthResponse(BaseModel):
    """Liveness report. `database` is informational, not a pass/fail."""

    status: str
    version: str
    env: str
    database: DatabaseStatus


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Report that the process is up, and whether the database is reachable."""
    settings = get_settings()
    return HealthResponse(
        status="ok",
        version=__version__,
        env=settings.app_env,
        database=await ping_database(),
    )
