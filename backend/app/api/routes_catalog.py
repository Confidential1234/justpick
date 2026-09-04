"""Reference data for the setup screen."""

from fastapi import APIRouter

from app.api.deps import DbSession
from app.api.schemas import GenreOut, ProviderOut
from app.services import catalog

router = APIRouter(tags=["catalog"])


@router.get("/providers", response_model=list[ProviderOut])
async def list_providers(db: DbSession) -> list[ProviderOut]:
    return [
        ProviderOut(id=p.id, name=p.name, logo_url=p.logo_url)
        for p in await catalog.list_providers(db)
    ]


@router.get("/genres", response_model=list[GenreOut])
async def list_genres(db: DbSession) -> list[GenreOut]:
    return [GenreOut(id=g.id, name=g.name) for g in await catalog.list_genres(db)]
