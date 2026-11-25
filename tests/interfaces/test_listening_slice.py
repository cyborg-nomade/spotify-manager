"""Real analytical HTTP contracts behind the deployed password middleware."""

import csv
from collections.abc import AsyncIterator
from collections.abc import Iterator
from contextlib import asynccontextmanager
from io import StringIO
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
from spotify_manager.application.listening_ports import ListeningVersionError
from spotify_manager.domain.listening_time import listening_identity
from spotify_manager.infrastructure.async_jobs import JobTasks
from spotify_manager.infrastructure.listening.library_runtime import LibraryRuntime
from spotify_manager.infrastructure.listening.runtime import ListeningRuntime
from spotify_manager.interfaces.http.listening import router
from spotify_manager.interfaces.http.listening_export import router as export_router
from spotify_manager.interfaces.http.listening_rediscovery import (
    router as revisit_router,
)
from spotify_manager.interfaces.http.playlist_export_runtime import (
    PlaylistExportRuntime,
)
from tests.support.listening import ListeningFixture
from tests.support.listening import listening_fixture
from tests.support.listening import sample_history
from tests.support.listening import scrobble
from tests.support.listening_export import OTHER
from tests.support.listening_export import OWNED
from tests.support.listening_export import FixturePlaylistGateway
from tests.support.listening_library import album
from tests.support.listening_library import publish_collection
from tests.support.listening_rediscovery import fixture_tracklists


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
        if hasattr(app.state, "export_tasks"):
            await app.state.export_tasks.close()
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
    app.state.listening_album_tracklists = fixture_tracklists()
    app.state.export_tasks = JobTasks()
    app.state.listening_exports = PlaylistExportRuntime(
        FixturePlaylistGateway(), app.state.export_tasks
    )
    app.include_router(router)
    app.include_router(revisit_router)
    app.include_router(export_router)
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
    assert client.get("/lastfm/analytics/scrobble-map").status_code == 401
    assert client.post("/lastfm/analytics/playlist-preview").status_code == 401
    assert client.post("/lastfm/analytics/playlist-preview/csv").status_code == 401
    assert client.get("/lastfm/analytics/rediscovery/artists").status_code == 401
    assert (
        client.post("/lastfm/analytics/rediscovery/album-tracklists").status_code == 401
    )
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
        "scrobble-map": "cells",
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


def test_map_cell_matches_pinned_records_through_the_repeated_dst_hour(
    listening_http: tuple[TestClient, ListeningFixture],
) -> None:
    """Count both local 02:00 hours and preserve duplicate times as raw points."""
    client, fixture = listening_http
    fixture.publish(
        [
            scrobble("2024-10-27T00:30:00"),
            scrobble("2024-10-27T01:35:00"),
            scrobble("2024-10-27T01:35:00"),
            scrobble("2024-10-27T02:05:00", "Béta"),
        ]
    )
    params = ready_parameters(client)
    params.update({"from": "2024-10-27", "to": "2024-10-27", "tz": "Europe/Berlin"})
    path = "/lastfm/analytics"
    mapped = client.get(path + "/scrobble-map", params=params).json()["data"]
    assert mapped["plays"] == 4 and len(mapped["points"]) == 4
    assert mapped["cells"] == [
        {"period": 0, "hour": 2, "plays": 3},
        {"period": 0, "hour": 3, "plays": 1},
    ]
    scoped = {
        **params,
        "hour": "2",
        "weekday": "6",
        "artist": listening_identity(("Alpha",)),
    }
    result = client.get(path + "/scrobble-map", params=scoped).json()["data"]
    records = client.get(path + "/scrobbles", params=scoped).json()["data"]
    assert result["plays"] == records["total"] == 3
    assert sorted(point["timestamp_ms"] for point in result["points"]) == sorted(
        row["timestamp_ms"] for row in records["items"]
    )


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
    details = {**params, "key": listening_identity(("Alpha",)), "q": "Alpha"}
    candidates = client.get("/lastfm/analytics/library/candidates", params=details)
    assert candidates.status_code == 200 and candidates.json()["data"]["items"] == []
    client.headers.pop("X-App-Password")
    assert client.get("/lastfm/analytics/library/status").status_code == 401
    assert client.get("/lastfm/analytics/library", params=params).status_code == 401
    assert (
        client.get("/lastfm/analytics/library/candidates", params=details).status_code
        == 401
    )


def test_library_candidates_keep_the_original_and_published_credits_pinned(
    listening_http: tuple[TestClient, ListeningFixture],
) -> None:
    """Search the verified mirror without treating a different edition as exact."""
    client, fixture = listening_http
    publish_collection(
        fixture, "albums", [album(), album("Record (Deluxe Edition)", 2)]
    )
    base = {**ready_parameters(client), "library_snapshot": ready_library(client)}
    params = {**base, "kind": "album", "key": listening_identity(("Alpha", "Record"))}
    path = "/lastfm/analytics/library/candidates"
    revision = fixture.service.snapshot().revision
    response = client.get(path, params=params)
    assert (
        response.status_code == 200
        and response.headers["Cache-Control"] == "private, no-store"
    )
    assert response.json()["snapshot"] == base["snapshot"]
    result = response.json()["data"]
    assert result["library_snapshot"] == base["library_snapshot"]
    assert (
        result["history"]["name"] == "Record" and result["history"]["artist"] == "Alpha"
    )
    assert result["total"] == 1 and result["items"][0]["exact_name"]
    search = {"q": "Alpha Record", "limit": 1, "page": 2}
    hits = client.get(path, params={**params, **search}).json()["data"]
    assert hits["total"] == 2 and hits["page"] == 2
    candidate = hits["items"][0]
    assert candidate["entry"]["name"] == "Record (Deluxe Edition)"
    assert candidate["entry"]["artist"] == "Alpha" and not candidate["exact_name"]
    by_uri = client.get(path, params={**params, "q": candidate["entry"]["uri"]})
    assert by_uri.json()["data"]["items"] == [candidate]
    assert fixture.service.snapshot().revision == revision


@pytest.mark.parametrize(
    ("extra", "code"),
    [
        ({"library_snapshot": "l1-" + "0" * 64}, 409),
        ({"snapshot": "v1-" + "0" * 64}, 409),
        ({"key": "0" * 64}, 404),
        ({"limit": 26}, 422),
    ],
)
def test_library_candidates_reject_expired_or_invalid_selections(
    listening_http: tuple[TestClient, ListeningFixture],
    extra: dict[str, object],
    code: int,
) -> None:
    """Reject unavailable versions and unknown original identities before reading."""
    client, _fixture = listening_http
    params = {
        **ready_parameters(client),
        "library_snapshot": ready_library(client),
        "kind": "album",
        "key": listening_identity(("Alpha", "Record")),
        **extra,
    }
    assert (
        client.get("/lastfm/analytics/library/candidates", params=params).status_code
        == code
    )


def test_playlist_csv_replays_the_same_pinned_proposal(
    listening_http: tuple[TestClient, ListeningFixture],
) -> None:
    """Keep tie order and the full proposal while paging; neutralize CSV formulas."""
    client, fixture = listening_http
    fixture.publish(
        [
            scrobble("2024-01-03T08:00:00", "Alpha", "=Early"),
            scrobble("2024-01-01T10:00:00", "Béta", "Other title"),
            scrobble("2024-01-01T10:00:00", "Alpha", "=Early"),
            scrobble("2024-01-01T11:00:00", "Alpha", "Edition"),
            scrobble("2024-01-02T10:00:00", "Unknown", "Missing"),
        ]
    )
    alpha_uri, beta_uri = "spotify:track:" + "a" * 22, "spotify:track:" + "b" * 22
    publish_collection(
        fixture,
        "tracks",
        [
            {"artist": "Alpha", "track": "=Early", "uri": alpha_uri},
            {"artist": "Béta", "track": "Other title", "uri": beta_uri},
        ],
    )
    params = {**ready_parameters(client), "library_snapshot": ready_library(client)}
    body = {
        "reviews": [{"key": listening_identity(("Alpha", "Edition")), "uri": alpha_uri}]
    }
    path = "/lastfm/analytics/playlist-preview"
    revision = fixture.service.snapshot().revision
    first = client.post(path, params={**params, "limit": 1}, json=body)
    assert (
        first.status_code == 200
        and first.headers["Cache-Control"] == "private, no-store"
    )
    assert first.json()["snapshot"] == params["snapshot"]
    data = first.json()["data"]
    assert data["library_snapshot"] == params["library_snapshot"]
    assert data["summary"] == {
        "selected_plays": 5,
        "playlist_tracks": 2,
        "duplicate_plays": 2,
        "unresolved_tracks": 1,
        "unresolved_plays": 1,
    }
    assert data["items"][0]["track"]["uri"] == beta_uri
    second = client.post(path, params={**params, "page": 2, "limit": 1}, json=body)
    assert second.json()["data"]["items"][0]["plays"] == 3
    export = client.post(path + "/csv", params=params, json=body)
    assert (
        export.status_code == 200
        and export.headers["Cache-Control"] == "private, no-store"
    )
    rows = list(csv.reader(StringIO(export.content.decode("utf-8-sig"))))
    assert [row[1] for row in rows[-2:]] == [beta_uri, alpha_uri]
    assert rows[-1][2] == "'=Early"
    assert ["Liked tracks snapshot", params["library_snapshot"]] in rows
    assert fixture.service.snapshot().revision == revision


def test_playlist_requires_current_versions_and_rejects_duplicate_review_keys(
    listening_http: tuple[TestClient, ListeningFixture],
) -> None:
    """Reject expired sources and protect the bounded list of browser reviews."""
    client, _fixture = listening_http
    scope = {**ready_parameters(client), "library_snapshot": ready_library(client)}
    path = "/lastfm/analytics/playlist-preview"
    empty = client.post(path, params={**scope, "view": "unresolved"}, json={})
    assert empty.json()["data"]["items"][0]["reason"] == "publication_unavailable"
    stale = {**scope, "library_snapshot": "l1-" + "0" * 64}
    assert client.post(path + "/csv", params=stale, json={}).status_code == 409
    stale = {**scope, "snapshot": "v1-" + "0" * 64}
    assert client.post(path, params=stale, json={}).status_code == 409
    choice = {"key": "0" * 64, "uri": "spotify:track:" + "x" * 22}
    assert (
        client.post(path, params=scope, json={"reviews": [choice, choice]}).status_code
        == 422
    )
    assert (
        client.post(
            path, params=scope, json={"reviews": [{**choice, "uri": "not-a-track"}]}
        ).status_code
        == 422
    )


def _rediscovery_history() -> list[dict[str, object]]:
    return [
        scrobble("2023-10-01T10:00:00", "Coverage", "Start"),
        scrobble("2024-01-02T10:00:00", "Alpha", "One", "Repeated visits"),
        scrobble("2024-01-09T10:00:00", "Alpha", "Two", "Repeated visits"),
        scrobble("2024-02-01T10:00:00", "Alpha", "Different A", "One sitting"),
        scrobble("2024-02-01T11:00:00", "Alpha", "Different B", "One sitting"),
        scrobble("2024-02-01T12:00:00", "Alpha", "Different C", "One sitting"),
        scrobble("2024-02-01T12:01:00", "One week", "Track A"),
        scrobble("2024-02-02T12:02:00", "One week", "Track B"),
        scrobble("2024-03-01T12:00:00", "Béta", "One"),
        scrobble("2024-03-08T12:00:00", "Béta", "Two"),
        scrobble("2024-12-25T12:00:00", "Béta", "One"),
        scrobble("2024-12-25T12:01:00", "Béta", "One"),
        scrobble("2024-12-25T12:02:00", "Béta", "Two"),
        scrobble("2025-01-02T12:00:00", "Alpha", "Partial final day"),
    ]


def test_artist_rediscovery_compares_complete_windows_and_suggests_albums(
    listening_http: tuple[TestClient, ListeningFixture],
) -> None:
    """Rank across weeks and distinct recent tracks, then suggest by album days."""
    client, fixture = listening_http
    fixture.publish(_rediscovery_history())
    publish_collection(fixture, "albums", [album("Repeated visits")])
    params = {
        **ready_parameters(client),
        "library_snapshot": ready_library(client),
        "history": "selection",
        "horizon": "30",
        "minimum_plays": "2",
        "minimum_weeks": "2",
    }
    path = "/lastfm/analytics/rediscovery/artists"
    response = client.get(path, params=params)
    assert (
        response.status_code == 200
        and response.headers["Cache-Control"] == "private, no-store"
    )
    data = response.json()["data"]
    assert data["dates"]["recent"]["end"] == "2025-01-01"
    assert data["qualifying"] == 2
    alpha, beta = data["artists"]
    assert (
        alpha["evidence"]["name"] == "Alpha" and alpha["evidence"]["recent_plays"] == 0
    )
    assert (
        beta["evidence"]["recent_tracks"] == 2 and beta["evidence"]["recent_plays"] == 3
    )
    assert [row["album"]["name"] for row in alpha["albums"]] == [
        "Repeated visits",
        "One sitting",
    ]
    assert alpha["albums"][0]["spotify"]["uri"] == album()["uri"]
    assert alpha["albums"][1]["spotify"] is None
    params.pop("library_snapshot")
    unpinned = client.get(path, params=params)
    assert unpinned.status_code == 200 and not unpinned.json()["data"]["albums_ready"]
    assert unpinned.json()["data"]["qualifying"] == 2
    assert client.get(path, params={**params, "to": "2024-12-31"}).status_code == 422


def test_rediscovery_tracklists_keep_album_and_disc_order_and_isolate_failures(
    listening_http: tuple[TestClient, ListeningFixture],
) -> None:
    """Read only saved editions and keep complete neighboring albums on failure."""
    client, fixture = listening_http
    uri = "spotify:album:" + "a" * 22
    broken = "spotify:album:" + "x" * 22
    records = [
        {"artist": "Alpha", "album": "Example", "uri": uri},
        {"artist": "Beta", "album": "Incomplete", "uri": broken},
    ]
    publish_collection(fixture, "albums", records)
    params = {**ready_parameters(client), "library_snapshot": ready_library(client)}
    revision = fixture.service.snapshot().revision
    path = "/lastfm/analytics/rediscovery/album-tracklists"
    response = client.post(path, params=params, json={"albums": [broken, uri]})
    assert (
        response.status_code == 200
        and response.headers["Cache-Control"] == "private, no-store"
    )
    data = response.json()["data"]
    assert data["library_snapshot"] == params["library_snapshot"]
    first, second = data["albums"]
    assert first["uri"] == broken and first["message"] and not first["tracks"]
    assert second["uri"] == uri and second["message"] is None
    assert [(row["disc"], row["track"]) for row in second["tracks"]] == [
        (1, 1),
        (1, 2),
        (2, 1),
    ]
    assert (
        client.post(path, params=params, json={"albums": [uri, uri]}).status_code == 422
    )
    unknown = "spotify:album:" + "z" * 22
    assert (
        client.post(path, params=params, json={"albums": [unknown]}).status_code == 422
    )
    assert (
        client.post(
            path,
            params={**params, "library_snapshot": "l1-" + "0" * 64},
            json={"albums": [uri]},
        ).status_code
        == 409
    )
    assert fixture.service.snapshot().revision == revision


def _wait_for_export(client: TestClient, path: str) -> dict[str, object]:
    until = monotonic() + 5
    while monotonic() < until:
        status = cast(dict[str, object], client.get(path).json()["status"])
        if status["stage"] not in {"queued", "running"}:
            return status
        sleep(0.01)
    raise AssertionError("Export did not finish in the local fixture.")


def test_confirmed_export_appends_the_exact_preview_once(
    listening_http: tuple[TestClient, ListeningFixture],
) -> None:
    """Prepare a protected owned destination without writing and then append once."""
    client, fixture = listening_http
    fixture.publish([scrobble("2024-01-02T10:00:00", "Alpha", "One")])
    uri = "spotify:track:" + "a" * 22
    publish_collection(
        fixture, "tracks", [{"artist": "Alpha", "track": "One", "uri": uri}]
    )
    params = {**ready_parameters(client), "library_snapshot": ready_library(client)}
    export = "/lastfm/analytics/playlist-export"
    assert (
        client.get(export + "/destinations", headers={"X-App-Password": ""}).status_code
        == 401
    )
    assert [row["identity"] for row in client.get(export + "/destinations").json()] == [
        OWNED
    ]
    gateway = cast(
        FixturePlaylistGateway,
        cast(FastAPI, client.app).state.listening_exports.spotify,
    )
    payload = {
        "source": {"kind": "history"},
        "destination": {"kind": "existing", "identity": OWNED},
    }
    response = client.post(export + "/plans", params=params, json=payload)
    assert (
        response.status_code == 200
        and response.headers["Cache-Control"] == "private, no-store"
    )
    prepared = response.json()
    assert (
        prepared["status"]["name"] == "Existing mix"
        and prepared["items"][0]["uri"] == uri
    )
    assert not gateway.writes and not gateway.creates
    path = export + "/plans/" + prepared["status"]["identity"]
    assert client.get(path).json() == prepared
    assert client.post(path + "/confirm").status_code == 200
    assert client.post(path + "/confirm").status_code == 200
    result = _wait_for_export(client, path)
    assert result["added"] == 1 and result["stage"] == "complete" and result["public"]
    assert gateway.writes == [(uri,)]
    payload["destination"]["identity"] = OTHER
    assert (
        client.post(export + "/plans", params=params, json=payload).status_code == 409
    )


def test_confirmed_rediscovery_export_creates_a_private_playlist_in_disc_order(
    listening_http: tuple[TestClient, ListeningFixture],
) -> None:
    """Prepare complete saved album tracks and create only after confirmation."""
    client, _fixture = listening_http
    params = {**ready_parameters(client), "library_snapshot": ready_library(client)}
    payload = {
        "source": {"kind": "albums", "albums": [album()["uri"]]},
        "destination": {"kind": "new", "name": "Rediscovery shortlist"},
    }
    export = "/lastfm/analytics/playlist-export"
    response = client.post(export + "/plans", params=params, json=payload)
    assert response.status_code == 200, response.text
    data = response.json()
    assert [item["name"] for item in data["items"]] == [
        "=Album opener",
        "Second song",
        "Disc two",
    ]
    assert not data["status"]["public"] and data["status"]["playlist_id"] is None
    path = export + "/plans/" + data["status"]["identity"]
    assert client.post(path + "/confirm").status_code == 200
    result = _wait_for_export(client, path)
    assert (
        result["stage"] == "complete" and result["added"] == 3 and not result["public"]
    )


def test_expired_publication_requires_a_fresh_review_before_export(
    listening_http: tuple[TestClient, ListeningFixture],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An obsolete review cannot create or append to a playlist."""
    client, _fixture = listening_http
    params = {**ready_parameters(client), "library_snapshot": ready_library(client)}
    prefix = "/lastfm/analytics/playlist-export/plans"
    response = client.post(
        prefix,
        params=params,
        json={
            "source": {"kind": "albums", "albums": [album()["uri"]]},
            "destination": {"kind": "new", "name": "Expired review"},
        },
    )
    assert response.status_code == 200
    state = cast(FastAPI, client.app).state
    monkeypatch.setattr(
        state.listening_library,
        "acquire",
        Mock(side_effect=ListeningVersionError("Expired publication")),
    )
    identity = response.json()["status"]["identity"]
    assert client.post(f"{prefix}/{identity}/confirm").status_code == 409
    gateway = cast(FixturePlaylistGateway, state.listening_exports.spotify)
    assert gateway.creates == 0 and not gateway.writes
