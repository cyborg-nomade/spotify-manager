"""Gated cached metadata views and explicit, bounded public lookup actions."""

from collections.abc import AsyncIterator
from collections.abc import Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from time import monotonic
from time import sleep

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from spotify_manager._auth import PasswordMiddleware
from spotify_manager.application import listening_tags
from spotify_manager.application.listening_tags import ListeningTagEnrichment
from spotify_manager.infrastructure.listening.tag_cache import ArtistTagCache
from spotify_manager.interfaces.http.listening import router as history_router
from spotify_manager.interfaces.http.listening_tags import router
from tests.interfaces.test_listening_slice import ready_parameters
from tests.support.listening import ListeningFixture
from tests.support.listening import listening_fixture
from tests.support.listening import sample_history
from tests.support.listening_tags import FixtureTagSource
from tests.support.listening_tags import tag_metadata


@asynccontextmanager
async def tag_lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Drain synthetic metadata work before closing the history fixture."""
    try:
        yield
    finally:
        await app.state.listening_tags.close()
        await app.state.listening.close()


@pytest.fixture
def tag_http(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[
    tuple[TestClient, ListeningFixture, ListeningTagEnrichment, FixtureTagSource]
]:
    """Serve real endpoints over independently owned synthetic publications."""
    monkeypatch.setattr(listening_tags, "REQUEST_INTERVAL", 0)
    fixture = listening_fixture(tmp_path)
    fixture.publish(sample_history())
    source = FixtureTagSource()
    stage = ListeningTagEnrichment(ArtistTagCache(tmp_path / "tags"), source)
    app = FastAPI(lifespan=tag_lifespan)
    app.state.listening = fixture.runtime
    app.state.listening_tags = stage
    app.include_router(history_router)
    app.include_router(router)
    app.add_middleware(PasswordMiddleware, password="tag-test-password")
    with TestClient(app) as client:
        client.headers["X-App-Password"] = "tag-test-password"
        yield client, fixture, stage, source


def finished(client: TestClient) -> dict[str, object]:
    """Wait for a small network-free explicit test batch to complete."""
    deadline = monotonic() + 10
    while monotonic() < deadline:
        status = client.get("/lastfm/analytics/tags/status").json()
        if status["state"] not in ("running", "cancelling"):
            return status
        sleep(0.001)
    raise AssertionError("Synthetic lookup batch did not complete.")


def test_cached_view_never_fetches_and_explicit_lookup_preserves_history(
    tag_http: tuple[
        TestClient, ListeningFixture, ListeningTagEnrichment, FixtureTagSource
    ],
) -> None:
    """Both generations stay pinned and no GET starts provider requests."""
    client, fixture, stage, source = tag_http
    params = ready_parameters(client)
    status = client.get("/lastfm/analytics/tags/status")
    assert status.headers["Cache-Control"] == "private, no-store"
    empty_token = status.json()["metadata_snapshot"]
    selected = {**params, "metadata_snapshot": empty_token, "per_artist": 3}
    response = client.get("/lastfm/analytics/tags", params=selected)
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "private, no-store"
    data = response.json()["data"]
    assert data["coverage"]["plays"] == 7 and data["coverage"]["tagged_plays"] == 0
    assert source.names == []
    revision = fixture.service.snapshot().revision
    assert (
        client.post(
            "/lastfm/analytics/tags/refresh", params={**params, "limit": 1}
        ).status_code
        == 200
    )
    completed = finished(client)
    assert completed["completed"] == 1 and source.names == ["Alpha"]
    result = client.get(
        "/lastfm/analytics/tags",
        params={**selected, "metadata_snapshot": completed["metadata_snapshot"]},
    ).json()["data"]
    assert result["coverage"]["tagged_plays"] == 5
    assert result["options"]["per_artist"] == 3
    assert (
        client.get("/lastfm/analytics/tags", params=selected).json()["data"][
            "coverage"
        ]["tagged_plays"]
        == 0
    )
    assert fixture.service.snapshot().revision == revision
    assert client.post("/lastfm/analytics/tags/cancel").status_code == 200


@pytest.mark.parametrize(
    "extra",
    [
        {"per_artist": 2},
        {"per_artist": 4},
        {"tag": "bad"},
        {"metadata_snapshot": "bad"},
        {"limit": 101},
        {"page": 0},
    ],
)
def test_tag_view_rejects_invalid_modes_and_unbounded_inputs(
    tag_http: tuple[
        TestClient, ListeningFixture, ListeningTagEnrichment, FixtureTagSource
    ],
    extra: dict[str, object],
) -> None:
    """Only documented modes and bounded evidence pages reach the domain."""
    client, _fixture, stage, _source = tag_http
    params = {
        **ready_parameters(client),
        "metadata_snapshot": stage.cache.current().snapshot,
        **extra,
    }
    assert client.get("/lastfm/analytics/tags", params=params).status_code == 422


def test_expired_metadata_and_disabled_provider_do_not_break_cached_views(
    tag_http: tuple[
        TestClient, ListeningFixture, ListeningTagEnrichment, FixtureTagSource
    ],
) -> None:
    """Version expiry, provider configuration and HTTP authentication stay explicit."""
    client, _fixture, stage, source = tag_http
    params = ready_parameters(client)
    expired = stage.cache.current().snapshot
    stage.cache.write(tag_metadata())
    stage.cache.write(tag_metadata("Beta"))
    assert (
        client.get(
            "/lastfm/analytics/tags", params={**params, "metadata_snapshot": expired}
        ).status_code
        == 409
    )
    source.configured = False
    assert (
        client.post("/lastfm/analytics/tags/refresh", params=params).status_code == 503
    )
    current = {**params, "metadata_snapshot": stage.cache.current().snapshot}
    assert client.get("/lastfm/analytics/tags", params=current).status_code == 200
    assert (
        client.post(
            "/lastfm/analytics/tags/refresh", params={**params, "limit": 51}
        ).status_code
        == 422
    )
    client.headers.pop("X-App-Password")
    assert client.get("/lastfm/analytics/tags/status").status_code == 401
    assert client.get("/lastfm/analytics/tags", params=current).status_code == 401
    assert (
        client.post("/lastfm/analytics/tags/refresh", params=params).status_code == 401
    )
    assert client.post("/lastfm/analytics/tags/cancel").status_code == 401
