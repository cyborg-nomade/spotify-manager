"""Real analytical HTTP contracts behind the deployed password middleware."""

from collections.abc import AsyncIterator
from collections.abc import Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from time import sleep
from typing import cast
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from spotify_manager._auth import PasswordMiddleware
from spotify_manager.domain.listening_time import listening_identity
from spotify_manager.infrastructure.listening.runtime import ListeningRuntime
from spotify_manager.interfaces.http.listening import router
from tests.support.listening import ListeningFixture
from tests.support.listening import listening_fixture
from tests.support.listening import sample_history


@asynccontextmanager
async def http_lifespan(app: FastAPI) -> AsyncIterator[None]:
    try:
        yield
    finally:
        runtime = cast(ListeningRuntime, app.state.listening)
        await runtime.close()


@pytest.fixture
def listening_http(tmp_path: Path) -> Iterator[tuple[TestClient, ListeningFixture]]:
    fixture = listening_fixture(tmp_path)
    fixture.publish(sample_history())
    app = FastAPI(lifespan=http_lifespan)
    app.state.listening = fixture.runtime
    app.include_router(router)
    app.add_middleware(PasswordMiddleware, password="listening-password")
    with TestClient(app) as client:
        client.headers["X-App-Password"] = "listening-password"
        yield client, fixture


def ready_parameters(client: TestClient) -> dict[str, str]:
    for _attempt in range(100):
        status = client.get("/lastfm/analytics/status").json()
        if status["metadata"] is not None:
            return {
                "from": "2024-01-01",
                "to": "2024-07-01",
                "tz": "UTC",
                "snapshot": status["metadata"]["snapshot"],
            }
        sleep(0.005)
    raise AssertionError("The synthetic index never became ready.")


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
