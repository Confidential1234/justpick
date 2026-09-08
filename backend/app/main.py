"""FastAPI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api import errors, routes_catalog, routes_decisions, routes_health
from app.config import get_settings
from app.db.session import dispose_engine
from app.services.clients import close_tmdb_client


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Release the TMDb connection pool and the database engine on shutdown."""
    yield
    await close_tmdb_client()
    await dispose_engine()


def create_app() -> FastAPI:
    """Build the application: CORS, routers, and the shared error handlers."""
    settings = get_settings()
    app = FastAPI(
        title="JustPick",
        description="Returns exactly one movie to watch, given your services and constraints.",
        version=__version__,
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-Session-Id"],
        # The browser cannot read a response header it was not told about, and the
        # client needs this one to adopt a server-minted session id.
        expose_headers=["X-Session-Id"],
    )
    app.include_router(routes_health.router, prefix=settings.api_v1_prefix)
    app.include_router(routes_catalog.router, prefix=settings.api_v1_prefix)
    app.include_router(routes_decisions.router, prefix=settings.api_v1_prefix)
    errors.register(app)
    return app


app = create_app()
