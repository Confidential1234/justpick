"""Application settings, loaded from the environment (or a local .env file)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "local"
    api_v1_prefix: str = "/api/v1"

    # Async SQLAlchemy URL, e.g. postgresql+asyncpg://user:pass@host/db
    # Optional: the decision engine and the health check run without a database.
    database_url: str | None = None

    # TMDb v4 Read Access Token (bearer).
    tmdb_api_token: str | None = None
    tmdb_base_url: str = "https://api.themoviedb.org/3"
    tmdb_image_base_url: str = "https://image.tmdb.org/t/p"

    # Comma-separated in the environment, e.g. CORS_ORIGINS=http://localhost:5173,https://app.example
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
