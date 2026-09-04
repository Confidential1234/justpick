"""Populate the reference tables from TMDb: genres, and US movie providers.

Idempotent — safe to re-run whenever TMDb adds a provider or renames a genre.

    python -m scripts.seed
"""

import asyncio
import sys

from app.config import get_settings
from app.db.models import Genre, Provider
from app.db.session import dispose_engine, get_engine, get_sessionmaker
from app.repositories import catalog
from app.tmdb.client import NETFLIX, PRIME_VIDEO, TMDbClient

# Everything TMDb knows about gets a row, so movie_providers can reference any of them.
# Only these are offered in the UI.
SUPPORTED_PROVIDERS = {NETFLIX, PRIME_VIDEO}


async def run() -> int:
    settings = get_settings()
    if not settings.tmdb_api_token:
        sys.exit("TMDB_API_TOKEN is not set (see backend/.env.example)")
    if get_engine() is None:
        sys.exit("DATABASE_URL is not set (see backend/.env.example)")

    async with TMDbClient(settings.tmdb_api_token, settings.tmdb_base_url) as client:
        genres = await client.genres()
        providers = await client.watch_providers("US")

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as db:
        await catalog.upsert_genres(db, [{"id": g.id, "name": g.name} for g in genres])
        await catalog.upsert_providers(
            db,
            [
                {
                    "id": p.id,
                    "name": p.name,
                    "logo_path": p.logo_path,
                    "is_enabled": p.id in SUPPORTED_PROVIDERS,
                }
                for p in providers
            ],
        )
        await db.commit()

        genre_count = await catalog.count_rows(db, Genre)
        provider_count = await catalog.count_rows(db, Provider)
        enabled = await catalog.enabled_providers(db)

    print(f"genres:    {genre_count}")
    print(f"providers: {provider_count} ({len(enabled)} enabled)")
    for provider in enabled:
        print(f"  [{provider.id}] {provider.name}")
    return 0


def main() -> int:
    try:
        return asyncio.run(_with_cleanup())
    except KeyboardInterrupt:
        return 130


async def _with_cleanup() -> int:
    try:
        return await run()
    finally:
        await dispose_engine()


if __name__ == "__main__":
    raise SystemExit(main())
