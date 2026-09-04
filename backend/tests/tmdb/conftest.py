"""Offline TMDb: real recorded payloads served through httpx's MockTransport.

The fixtures under fixtures/ are genuine TMDb responses, trimmed. That matters more than
convenience — hand-written payloads only ever contain the fields you remembered to
include, and the parsing bugs worth catching are in the fields you forgot.
"""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.tmdb.client import TMDbClient

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


class RecordingTransport(httpx.MockTransport):
    """MockTransport that remembers what it was asked for."""

    def __init__(self, handler: Callable[[httpx.Request], httpx.Response]) -> None:
        self.requests: list[httpx.Request] = []

        def recording(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return handler(request)

        super().__init__(recording)

    @property
    def call_count(self) -> int:
        return len(self.requests)

    @property
    def last(self) -> httpx.Request:
        return self.requests[-1]


def client_for(
    handler: Callable[[httpx.Request], httpx.Response], **kwargs: Any
) -> tuple[TMDbClient, RecordingTransport]:
    transport = RecordingTransport(handler)
    kwargs.setdefault("backoff_base", 0.0)  # no real sleeping in tests
    return TMDbClient(token="test-token", transport=transport, **kwargs), transport


def always(payload: dict[str, Any], status: int = 200) -> Callable[[httpx.Request], httpx.Response]:
    return lambda _request: httpx.Response(status, json=payload)


@pytest.fixture
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Swallow backoff sleeps and record how long they would have been."""
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr("app.tmdb.client.asyncio.sleep", fake_sleep)
    return slept
