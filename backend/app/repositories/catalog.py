"""Reads and writes for the TMDb cache.

Takes plain row mappings rather than TMDb objects: this layer must not know that TMDb
exists (see tests/test_layering.py), so translating an API payload into these rows is the
service layer's job.
"""

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Genre, Movie, MovieGenre, MovieProvider, Provider

Row = Mapping[str, Any]

# Availability churns; a day-old answer is close enough and saves a call per candidate.
PROVIDER_TTL = timedelta(hours=24)


async def upsert_genres(db: AsyncSession, rows: Sequence[Row]) -> int:
    if not rows:
        return 0
    stmt = insert(Genre).values(list(rows))
    await db.execute(
        stmt.on_conflict_do_update(index_elements=[Genre.id], set_={"name": stmt.excluded.name})
    )
    return len(rows)


async def upsert_providers(db: AsyncSession, rows: Sequence[Row]) -> int:
    if not rows:
        return 0
    stmt = insert(Provider).values(list(rows))
    await db.execute(
        stmt.on_conflict_do_update(
            index_elements=[Provider.id],
            set_={
                "name": stmt.excluded.name,
                "logo_path": stmt.excluded.logo_path,
                "is_enabled": stmt.excluded.is_enabled,
            },
        )
    )
    return len(rows)


async def upsert_movies(db: AsyncSession, rows: Sequence[Row]) -> int:
    """Insert or refresh movie metadata.

    Deliberately does not touch runtime_minutes or details_synced_at: discover results do
    not carry a runtime, and a blind upsert would erase one we had already paid a details
    call to learn.
    """
    if not rows:
        return 0
    stmt = insert(Movie).values(list(rows))
    updatable = {
        column: stmt.excluded[column]
        for column in (
            "title",
            "original_title",
            "overview",
            "release_date",
            "vote_average",
            "vote_count",
            "popularity",
            "poster_path",
            "backdrop_path",
            "original_language",
            "adult",
        )
        if column in rows[0]
    }
    updatable["updated_at"] = func.now()
    await db.execute(stmt.on_conflict_do_update(index_elements=[Movie.tmdb_id], set_=updatable))
    return len(rows)


async def replace_movie_genres(db: AsyncSession, movie_id: int, genre_ids: Sequence[int]) -> None:
    await db.execute(delete(MovieGenre).where(MovieGenre.movie_id == movie_id))
    if genre_ids:
        await db.execute(
            insert(MovieGenre)
            .values([{"movie_id": movie_id, "genre_id": g} for g in genre_ids])
            .on_conflict_do_nothing()
        )


async def link_genres(db: AsyncSession, pairs: Sequence[tuple[int, int]]) -> int:
    """Bulk (movie_id, genre_id) linking, ignoring pairs that already exist."""
    if not pairs:
        return 0
    await db.execute(
        insert(MovieGenre)
        .values([{"movie_id": m, "genre_id": g} for m, g in pairs])
        .on_conflict_do_nothing()
    )
    return len(pairs)


async def record_availability(
    db: AsyncSession, movie_id: int, provider_ids: Sequence[int], region: str = "US"
) -> None:
    """Note which services carry a film, refreshing the verification timestamp."""
    if not provider_ids:
        return
    stmt = insert(MovieProvider).values(
        [
            {
                "movie_id": movie_id,
                "provider_id": provider_id,
                "region": region,
                "monetization_type": "flatrate",
                "last_verified_at": datetime.now(UTC),
            }
            for provider_id in provider_ids
        ]
    )
    await db.execute(
        stmt.on_conflict_do_update(
            index_elements=[
                MovieProvider.movie_id,
                MovieProvider.provider_id,
                MovieProvider.region,
                MovieProvider.monetization_type,
            ],
            set_={"last_verified_at": stmt.excluded.last_verified_at},
        )
    )


async def set_movie_details(
    db: AsyncSession, movie_id: int, runtime_minutes: int | None
) -> None:
    """Record the result of a details call, including a null runtime.

    Storing details_synced_at even when the runtime is unknown is the point: without it
    we would re-request the same film forever hoping for a runtime TMDb does not have.
    """
    await db.execute(
        insert(Movie)
        .values(
            tmdb_id=movie_id,
            title="",
            runtime_minutes=runtime_minutes,
            details_synced_at=datetime.now(UTC),
        )
        .on_conflict_do_update(
            index_elements=[Movie.tmdb_id],
            set_={
                "runtime_minutes": runtime_minutes,
                "details_synced_at": datetime.now(UTC),
            },
        )
    )


async def cached_runtimes(db: AsyncSession, movie_ids: Sequence[int]) -> dict[int, int]:
    """Runtimes we already know, so scoring is not blind to them.

    This is what makes runtime_fit stop being inert. Discover never returns runtimes, so
    a cold candidate scores a neutral 0.5; every details call for a chosen film fills one
    in, and the weight does progressively more work as the cache warms.
    """
    if not movie_ids:
        return {}
    result = await db.execute(
        select(Movie.tmdb_id, Movie.runtime_minutes).where(
            Movie.tmdb_id.in_(movie_ids), Movie.runtime_minutes.is_not(None)
        )
    )
    return {tmdb_id: runtime for tmdb_id, runtime in result.all() if runtime is not None}


async def enabled_providers(db: AsyncSession) -> list[Provider]:
    result = await db.execute(
        select(Provider).where(Provider.is_enabled.is_(True)).order_by(Provider.name)
    )
    return list(result.scalars())


async def get_movie(db: AsyncSession, tmdb_id: int) -> Movie | None:
    """A cached movie with its genre and provider links eagerly loaded."""
    return await db.get(Movie, tmdb_id)


async def providers_for_movie(
    db: AsyncSession, tmdb_id: int, provider_ids: Sequence[int], region: str = "US"
) -> list[Provider]:
    """Which of the given services carry this film, per the cache."""
    if not provider_ids:
        return []
    result = await db.execute(
        select(Provider)
        .join(MovieProvider, MovieProvider.provider_id == Provider.id)
        .where(
            MovieProvider.movie_id == tmdb_id,
            MovieProvider.region == region,
            Provider.id.in_(provider_ids),
        )
        .order_by(Provider.name)
    )
    return list(result.scalars())


async def genres_for_movie(db: AsyncSession, tmdb_id: int) -> list[Genre]:
    result = await db.execute(
        select(Genre)
        .join(MovieGenre, MovieGenre.genre_id == Genre.id)
        .where(MovieGenre.movie_id == tmdb_id)
        .order_by(Genre.name)
    )
    return list(result.scalars())


async def all_genres(db: AsyncSession) -> list[Genre]:
    return list((await db.execute(select(Genre).order_by(Genre.name))).scalars())


async def count_rows(db: AsyncSession, model: type) -> int:
    return (await db.execute(select(func.count()).select_from(model))).scalar_one()
