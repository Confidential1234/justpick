"""Reference data for the setup screen."""

from fastapi import APIRouter

from app.api.deps import DbSession
from app.api.schemas import GenreOut, ProviderOut
from app.services import catalog

router = APIRouter(tags=["catalog"])


@router.get("/providers", response_model=list[ProviderOut])
async def list_providers(db: DbSession) -> list[ProviderOut]:
    """The streaming services the app supports. Empty before the seed script has run."""
    return [
        ProviderOut(id=p.id, name=p.name, logo_url=p.logo_url)
        for p in await catalog.list_providers(db)
    ]


@router.get("/genres", response_model=list[GenreOut])
async def list_genres(db: DbSession) -> list[GenreOut]:
    """Every genre available for the mood picker."""
    return [GenreOut(id=g.id, name=g.name) for g in await catalog.list_genres(db)]
