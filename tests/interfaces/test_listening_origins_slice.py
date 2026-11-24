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
from spotify_manager.application import listening_origins
from spotify_manager.application.listening_origins import ListeningOriginEnrichment
from spotify_manager.infrastructure.listening.origin_cache import ArtistOriginCache
from spotify_manager.interfaces.http.listening import router as history_router
from spotify_manager.interfaces.http.listening_origins import router
from tests.interfaces.test_listening_slice import ready_parameters
from tests.support.listening import ListeningFixture
from tests.support.listening import listening_fixture
from tests.support.listening import sample_history
from tests.support.listening_origins import FixtureOriginArchive
from tests.support.listening_origins import FixtureOriginSource
from tests.support.listening_origins import origin_metadata


@asynccontextmanager
async def origin_lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Drain synthetic metadata work before closing the history fixture."""
    try:
        await app.state.listening_origins.restore()
        yield
    finally:
        await app.state.listening_origins.close()
        await app.state.listening.close()


@pytest.fixture
def origin_http(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[
    tuple[TestClient, ListeningFixture, ListeningOriginEnrichment, FixtureOriginSource]
]:
    """Serve real endpoints over independently owned synthetic publications."""
    monkeypatch.setattr(listening_origins, "REQUEST_INTERVAL", 0)
    fixture = listening_fixture(tmp_path)
    fixture.publish(sample_history())
    source = FixtureOriginSource()
    stage = ListeningOriginEnrichment(
        ArtistOriginCache(tmp_path / "tags"), source, FixtureOriginArchive()
    )
    app = FastAPI(lifespan=origin_lifespan)
    app.state.listening = fixture.runtime
    app.state.listening_origins = stage
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
        status = client.get("/lastfm/analytics/origins/status").json()
        if status["state"] not in ("running", "cancelling"):
            return status
        sleep(0.001)
    raise AssertionError("Synthetic lookup batch did not complete.")


def test_cached_view_never_fetches_and_explicit_lookup_preserves_history(
    origin_http: tuple[
        TestClient, ListeningFixture, ListeningOriginEnrichment, FixtureOriginSource
    ],
) -> None:
    """Both generations stay pinned and no GET starts provider requests."""
    client, fixture, stage, source = origin_http
    params = ready_parameters(client)
    status = client.get("/lastfm/analytics/origins/status")
    assert status.headers["Cache-Control"] == "private, no-store"
    empty_token = status.json()["metadata_snapshot"]
    selected = {**params, "metadata_snapshot": empty_token, "evidence": "all"}
    response = client.get("/lastfm/analytics/origins", params=selected)
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "private, no-store"
    data = response.json()["data"]
    assert data["coverage"]["plays"] == 7 and data["coverage"]["country_plays"] == 0
    assert source.names == []
    revision = fixture.service.snapshot().revision
    assert (
        client.post(
            "/lastfm/analytics/origins/refresh", params={**params, "limit": 1}
        ).status_code
        == 200
    )
    completed = finished(client)
    assert completed["completed"] == 1 and source.names == ["Alpha"]
    result = client.get(
        "/lastfm/analytics/origins",
        params={**selected, "metadata_snapshot": completed["metadata_snapshot"]},
    ).json()["data"]
    assert result["coverage"]["country_plays"] == 5
    assert result["options"]["evidence"] == "all"
    assert (
        client.get("/lastfm/analytics/origins", params=selected).json()["data"][
            "coverage"
        ]["country_plays"]
        == 0
    )
    assert fixture.service.snapshot().revision == revision
    assert client.post("/lastfm/analytics/origins/cancel").status_code == 200


@pytest.mark.parametrize(
    "extra",
    [
        {"country": "bad"},
        {"evidence": "guessed"},
        {"metadata_snapshot": "bad"},
        {"limit": 101},
        {"page": 0},
    ],
)
def test_tag_view_rejects_invalid_modes_and_unbounded_inputs(
    origin_http: tuple[
        TestClient, ListeningFixture, ListeningOriginEnrichment, FixtureOriginSource
    ],
    extra: dict[str, object],
) -> None:
    """Only documented modes and bounded evidence pages reach the domain."""
    client, _fixture, stage, _source = origin_http
    params = {
        **ready_parameters(client),
        "metadata_snapshot": stage.cache.current().snapshot,
        **extra,
    }
    assert client.get("/lastfm/analytics/origins", params=params).status_code == 422


def test_expired_metadata_and_disabled_provider_do_not_break_cached_views(
    origin_http: tuple[
        TestClient, ListeningFixture, ListeningOriginEnrichment, FixtureOriginSource
    ],
) -> None:
    """Version expiry, provider configuration and HTTP authentication stay explicit."""
    client, _fixture, stage, source = origin_http
    params = ready_parameters(client)
    expired = stage.cache.current().snapshot
    stage.cache.write(origin_metadata())
    stage.cache.write(origin_metadata("Beta"))
    assert (
        client.get(
            "/lastfm/analytics/origins", params={**params, "metadata_snapshot": expired}
        ).status_code
        == 409
    )
    source.configured = False
    assert (
        client.post("/lastfm/analytics/origins/refresh", params=params).status_code
        == 503
    )
    current = {**params, "metadata_snapshot": stage.cache.current().snapshot}
    assert client.get("/lastfm/analytics/origins", params=current).status_code == 200
    assert (
        client.post(
            "/lastfm/analytics/origins/refresh", params={**params, "limit": 26}
        ).status_code
        == 422
    )
    client.headers.pop("X-App-Password")
    assert client.get("/lastfm/analytics/origins/status").status_code == 401
    assert client.get("/lastfm/analytics/origins", params=current).status_code == 401
    assert (
        client.post("/lastfm/analytics/origins/refresh", params=params).status_code
        == 401
    )
    assert client.post("/lastfm/analytics/origins/cancel").status_code == 401


def test_full_history_loader_ignores_dates_and_skips_completed_outcomes(
    origin_http: tuple[
        TestClient, ListeningFixture, ListeningOriginEnrichment, FixtureOriginSource
    ],
) -> None:
    """Queue across published history and keep lookups behind authentication."""
    client, _fixture, _stage, source = origin_http
    params = {"snapshot": ready_parameters(client)["snapshot"], "from": "2099-01-01"}
    path = "/lastfm/analytics/origins/backfill"
    first = client.post(path, params={**params, "limit": 1})
    assert first.status_code == 200 and first.json()["durable"]
    assert finished(client)["completed"] == 1
    assert source.names == ["Alpha"]
    assert client.post(path, params=params).status_code == 200
    assert finished(client)["completed"] == 2
    assert source.names == ["Alpha", "Beta", "Béta"]
    assert client.post(path, params=params).status_code == 200
    assert finished(client)["completed"] == 0
    client.headers.pop("X-App-Password")
    assert client.post(path, params=params).status_code == 401
