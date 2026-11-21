"""Real analytical HTTP contracts behind the deployed password middleware."""

from collections.abc import AsyncIterator
from collections.abc import Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic
from time import sleep
from typing import cast
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from spotify_manager._auth import PasswordMiddleware
from spotify_manager.domain.listening_time import listening_identity
from spotify_manager.infrastructure.listening.library_runtime import LibraryRuntime
from spotify_manager.infrastructure.listening.runtime import ListeningRuntime
from spotify_manager.interfaces.http.listening import router
from tests.support.listening import ListeningFixture
from tests.support.listening import listening_fixture
from tests.support.listening import sample_history
from tests.support.listening_library import album
from tests.support.listening_library import publish_collection


class DelayedListeningRuntime(ListeningRuntime):
    """Model a correct index build delayed by a busy CI worker."""

    def refresh_source(self) -> None:
        """Delay only this synthetic resource, then run the real index build."""
        sleep(2)
        super().refresh_source()


@asynccontextmanager
async def http_lifespan(app: FastAPI) -> AsyncIterator[None]:
    try:
        yield
    finally:
        if hasattr(app.state, "listening_library"):
            await app.state.listening_library.close()
        runtime = cast(ListeningRuntime, app.state.listening)
        await runtime.close()


@pytest.fixture
def listening_http(tmp_path: Path) -> Iterator[tuple[TestClient, ListeningFixture]]:
    fixture = listening_fixture(tmp_path)
    fixture.publish(sample_history())
    publish_collection(fixture, "albums", [album()])
    app = FastAPI(lifespan=http_lifespan)
    app.state.listening = fixture.runtime
    app.state.listening_library = LibraryRuntime(fixture.service)
    app.include_router(router)
    app.add_middleware(PasswordMiddleware, password="listening-password")
    with TestClient(app) as client:
        client.headers["X-App-Password"] = "listening-password"
        yield client, fixture


def ready_parameters(client: TestClient) -> dict[str, str]:
    deadline = monotonic() + 10
    while monotonic() < deadline:
        status = client.get("/lastfm/analytics/status").json()
        if status["metadata"] is not None:
            return {
                "from": "2024-01-01",
                "to": "2024-07-01",
                "tz": "UTC",
                "snapshot": status["metadata"]["snapshot"],
            }
        assert status["state"] == "building", status["message"]
        sleep(0.01)
    raise AssertionError("The synthetic index did not become ready within 10 seconds.")


def test_readiness_wait_accepts_a_delayed_successful_index(tmp_path: Path) -> None:
    fixture = listening_fixture(tmp_path)
    fixture.publish(sample_history())
    runtime = DelayedListeningRuntime(fixture.service, TemporaryDirectory(dir=tmp_path))
    app = FastAPI(lifespan=http_lifespan)
    app.state.listening = runtime
    app.include_router(router)
    with TestClient(app) as client:
        params = ready_parameters(client)
        assert params["snapshot"].startswith("v1-")
        assert (
            client.get("/lastfm/analytics/overview", params=params).status_code == 200
        )


def test_authentication_precedes_any_index_acquisition(
    listening_http: tuple[TestClient, ListeningFixture], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, fixture = listening_http
    probe = Mock(side_effect=AssertionError("unauthenticated source check"))
    monkeypatch.setattr(fixture.runtime, "status", probe)
    client.headers.pop("X-App-Password")
    assert client.get("/lastfm/analytics/status").status_code == 401
    assert (
        client.get(
            "/lastfm/analytics/status", headers={"X-App-Password": "wrong"}
        ).status_code
        == 401
    )
    assert client.get("/lastfm/analytics/overview").status_code == 401
    probe.assert_not_called()


def test_endpoints_share_one_snapshot_and_exact_filters(
    listening_http: tuple[TestClient, ListeningFixture],
) -> None:
    client, fixture = listening_http
    revision = fixture.service.snapshot().revision
    params = ready_parameters(client)
    expected = {
        "overview": "counts",
        "activity": "days",
        "rankings": "items",
        "evolution": "series",
        "scrobbles": "items",
        "discovery": "cohorts",
        "rediscovery": "items",
        "comparison": "items",
        "eras": "similarities",
        "on-this-day": "days",
    }
    for endpoint, field in expected.items():
        response = client.get("/lastfm/analytics/" + endpoint, params=params)
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "private, no-store"
        body = response.json()
        assert body["snapshot"] == params["snapshot"]
        assert body["filters"]["timezone"] == "UTC"
        assert body["filters"]["start"] == params["from"]
        assert field in body["data"]
    assert fixture.service.snapshot().revision == revision


def test_details_and_record_pages_keep_original_names(
    listening_http: tuple[TestClient, ListeningFixture],
) -> None:
    client, _fixture = listening_http
    params = ready_parameters(client)
    key = listening_identity(("Alpha",))
    detail = client.get(
        f"/lastfm/analytics/entities/artist/{key}", params=params
    ).json()["data"]
    assert detail["lifetime"]["plays"] == 5
    selected = dict(params, kind="artist", key=key, page="2", limit="2")
    response = client.get("/lastfm/analytics/scrobbles", params=selected)
    assert response.status_code == 200
    assert response.json()["data"]["total"] == 5
    assert response.json()["data"]["items"][0]["artist"] == "ALPHA"
    unknown = client.get("/lastfm/analytics/entities/artist/" + "0" * 64, params=params)
    assert unknown.status_code == 404


@pytest.mark.parametrize(
    "change",
    [
        {"from": "2025-01-01"},
        {"from": "1899-01-01"},
        {"to": "2100-01-01"},
        {"from": "1900-01-01", "to": "2050-01-01"},
        {"tz": "Not/AZone"},
        {"tz": "/etc/passwd"},
        {"snapshot": "bad"},
        {"weekday": "7"},
        {"hour": "24"},
        {"artist": "bad"},
    ],
)
def test_query_validation_is_explicit(
    listening_http: tuple[TestClient, ListeningFixture], change: dict[str, str]
) -> None:
    client, _fixture = listening_http
    params = ready_parameters(client)
    params.update(change)
    assert client.get("/lastfm/analytics/overview", params=params).status_code == 422


@pytest.mark.parametrize(
    "endpoint,change",
    [
        ("rankings", {"limit": "101"}),
        ("rankings", {"page": "0"}),
        ("rankings", {"kind": "invalid"}),
        ("rankings", {"q": "x" * 101}),
        ("scrobbles", {"limit": "201"}),
        ("scrobbles", {"kind": "artist"}),
        ("scrobbles", {"key": "0" * 64}),
        ("discovery", {"hour": "12"}),
        ("on-this-day", {"hour": "12"}),
        ("on-this-day", {"weekday": "1"}),
        ("rediscovery", {"weekday": "1"}),
        ("rediscovery", {"minimum_gap": "-1"}),
        ("evolution", {"grain": "invalid"}),
    ],
)
def test_page_bounds_and_incompatible_filters_are_rejected(
    listening_http: tuple[TestClient, ListeningFixture],
    endpoint: str,
    change: dict[str, str],
) -> None:
    client, _fixture = listening_http
    params = ready_parameters(client)
    params.update(change)
    assert client.get("/lastfm/analytics/" + endpoint, params=params).status_code == 422


def test_cold_and_expired_generations_have_distinct_responses(
    listening_http: tuple[TestClient, ListeningFixture],
) -> None:
    client, _fixture = listening_http
    params = {"from": "2024-01-01", "to": "2024-07-01", "snapshot": "v1-" + "0" * 64}
    assert client.get("/lastfm/analytics/overview", params=params).status_code == 503
    ready_parameters(client)
    assert client.get("/lastfm/analytics/overview", params=params).status_code == 409


def test_explicit_refresh_is_read_only(
    listening_http: tuple[TestClient, ListeningFixture],
) -> None:
    client, fixture = listening_http
    ready_parameters(client)
    revision = fixture.service.snapshot().revision
    response = client.get("/lastfm/analytics/status", params={"refresh": "true"})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert fixture.service.snapshot().revision == revision


def ready_library(client: TestClient) -> str:
    """Wait for a complete collection generation independently of history."""
    deadline = monotonic() + 10
    while monotonic() < deadline:
        response = client.get("/lastfm/analytics/library/status")
        assert response.status_code == 200
        status = response.json()
        if status["snapshot"] is not None:
            return str(status["snapshot"])
        assert status["state"] == "building"
        sleep(0.01)
    raise AssertionError("Collection publication did not become ready.")


def test_library_comparison_pins_both_sources_and_keeps_selected_counts(
    listening_http: tuple[TestClient, ListeningFixture],
) -> None:
    """Reconcile names and plays through the actual gated HTTP resource path."""
    client, fixture = listening_http
    params = {**ready_parameters(client), "library_snapshot": ready_library(client)}
    before = fixture.service.snapshot().revision
    response = client.get("/lastfm/analytics/library", params=params)
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "private, no-store"
    body = response.json()
    assert body["snapshot"] == params["snapshot"]
    data = body["data"]
    assert data["library_snapshot"] == params["library_snapshot"]
    assert data["source"]["state"] == "ready"
    assert sum(item["plays"] for item in data["coverage"]) == 6
    assert data["items"][0]["history"]["plays"] == 4
    assert data["items"][0]["status"] == "name_match"
    params["from"] = params["to"]
    narrow = client.get("/lastfm/analytics/library", params=params).json()["data"]
    assert narrow["items"][0]["history"]["plays"] == 1
    assert fixture.service.snapshot().revision == before


@pytest.mark.parametrize(
    "extra,code",
    [
        ({"kind": "unknown"}, 422),
        ({"status": "present"}, 422),
        ({"minimum_plays": 0}, 422),
        ({"limit": 101}, 422),
        ({"library_snapshot": "invalid"}, 422),
        ({"library_snapshot": "l1-" + "0" * 64}, 409),
    ],
)
def test_library_comparison_rejects_invalid_or_expired_versions(
    listening_http: tuple[TestClient, ListeningFixture],
    extra: dict[str, object],
    code: int,
) -> None:
    """Protect bounded comparison options and independent generation identity."""
    client, _fixture = listening_http
    params = {
        **ready_parameters(client),
        "library_snapshot": ready_library(client),
        **extra,
    }
    assert client.get("/lastfm/analytics/library", params=params).status_code == code


def test_missing_library_is_unknown_and_new_routes_remain_gated(
    listening_http: tuple[TestClient, ListeningFixture],
) -> None:
    """Unavailable follows do not imply absence and no new data route bypasses auth."""
    client, _fixture = listening_http
    params = {
        **ready_parameters(client),
        "library_snapshot": ready_library(client),
        "kind": "artist",
    }
    result = client.get("/lastfm/analytics/library", params=params).json()["data"]
    assert result["source"]["state"] == "missing"
    assert all(item["status"] == "unavailable" for item in result["items"])
    client.headers.pop("X-App-Password")
    assert client.get("/lastfm/analytics/library/status").status_code == 401
    assert client.get("/lastfm/analytics/library", params=params).status_code == 401
