"""Application settings, loaded from the environment (or a local .env file)."""

from functools import lru_cache
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "local"
    api_v1_prefix: str = "/api/v1"

    # Async SQLAlchemy URL, e.g. postgresql+asyncpg://user:pass@host/db
    # Optional: the decision engine and the health check run without a database.
    # Accepts a connection string pasted straight from a hosting dashboard; see
    # _normalise_database_url for what gets rewritten.
    database_url: str | None = None

    # TMDb v4 Read Access Token (bearer).
    tmdb_api_token: str | None = None
    tmdb_base_url: str = "https://api.themoviedb.org/3"
    tmdb_image_base_url: str = "https://image.tmdb.org/t/p"

    # Comma-separated in the environment, e.g. CORS_ORIGINS=http://localhost:5173,https://app.example
    #
    # NoDecode is required: without it pydantic-settings tries to JSON-parse any complex
    # field coming from the environment, so a plain comma-separated list raises at import
    # time and the app never boots. Hosting dashboards take plain strings, not JSON.
    cors_origins: Annotated[list[str], NoDecode] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_comma_separated(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("database_url", mode="before")
    @classmethod
    def _normalise_database_url(cls, value: object) -> object:
        """Make a dashboard-copied connection string usable by asyncpg.

        Hosting providers hand out libpq URLs, and pasting one in unedited fails in two
        ways that are annoying to diagnose: the wrong driver is loaded, and asyncpg
        rejects libpq-only query options like sslmode with an opaque TypeError. Rewriting
        here means the deploy dashboard can hold whatever the provider gave you.
        """
        if not isinstance(value, str) or not value.strip():
            return value

        url = value.strip()
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                url = f"postgresql+asyncpg://{url[len(prefix) :]}"
                break

        head, separator, query = url.partition("?")
        if not separator:
            return url

        # TLS is configured on the engine instead - see app/db/session.py.
        libpq_only = {"sslmode", "channel_binding", "sslrootcert", "options"}
        kept = [
            pair
            for pair in query.split("&")
            if pair and pair.split("=", 1)[0] not in libpq_only
        ]
        return f"{head}?{'&'.join(kept)}" if kept else head


@lru_cache
def get_settings() -> Settings:
    return Settings()
