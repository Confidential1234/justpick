"""The setup screen's reference data."""

from typing import Any

import httpx
import pytest

from app.services.views import GenreOption, ProviderOption


def stub(monkeypatch: pytest.MonkeyPatch, name: str, result: Any) -> None:
    async def fake(*args: Any, **kwargs: Any) -> Any:
        return result

    monkeypatch.setattr(f"app.services.catalog.{name}", fake)


async def test_providers_are_listed(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub(
        monkeypatch,
        "list_providers",
        [
            ProviderOption(id=8, name="Netflix", logo_url="https://img/netflix.png"),
            ProviderOption(id=9, name="Amazon Prime Video", logo_url=None),
        ],
    )
    response = await client.get("/api/v1/providers")

    assert response.status_code == 200
    assert response.json() == [
        {"id": 8, "name": "Netflix", "logo_url": "https://img/netflix.png"},
        {"id": 9, "name": "Amazon Prime Video", "logo_url": None},
    ]


async def test_genres_are_listed(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub(monkeypatch, "list_genres", [GenreOption(id=28, name="Action")])
    response = await client.get("/api/v1/genres")

    assert response.status_code == 200
    assert response.json() == [{"id": 28, "name": "Action"}]


async def test_an_empty_catalogue_is_not_an_error(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Before the seed script has run, these are simply empty."""
    stub(monkeypatch, "list_providers", [])
    response = await client.get("/api/v1/providers")

    assert response.status_code == 200
    assert response.json() == []
