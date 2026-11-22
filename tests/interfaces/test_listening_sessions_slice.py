"""Exercise real protected session reads, context pinning and record boundaries."""

from collections.abc import AsyncIterator
from collections.abc import Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import cast
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from spotify_manager._auth import PasswordMiddleware
from spotify_manager.domain.listening_time import listening_identity
from spotify_manager.infrastructure.listening.runtime import ListeningRuntime
from spotify_manager.interfaces.http.listening import router
from spotify_manager.interfaces.http.listening_sessions import router as session_router
from tests.interfaces.test_listening_slice import ready_parameters
from tests.support.listening import ListeningFixture
from tests.support.listening import listening_fixture
from tests.support.listening import scrobble
from tests.support.listening import timestamp
from tests.support.listening_sessions import session_history


@asynccontextmanager
async def session_lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Close the test's owned index runtime on every exit.

    Args:
        app: Synthetic application owning one runtime.

    Yields:
        Control while the synthetic application is running.
    """
    try:
        yield
    finally:
        await cast(ListeningRuntime, app.state.listening).close()


@pytest.fixture
def session_http(tmp_path: Path) -> Iterator[tuple[TestClient, ListeningFixture]]:
    """Serve independently published rows behind the real password middleware.

    Args:
        tmp_path: Isolated source, state and derived index directory.

    Yields:
        Credentialed real client and its independently owned publication.
    """
    fixture = listening_fixture(tmp_path)
    fixture.publish(session_history())
    app = FastAPI(lifespan=session_lifespan)
    app.state.listening = fixture.runtime
    app.include_router(router)
    app.include_router(session_router)
    app.add_middleware(PasswordMiddleware, password="session-password")
    with TestClient(app) as client:
        client.headers["X-App-Password"] = "session-password"
        yield client, fixture


@pytest.mark.parametrize("path", ["", "/1704110400000/records"])
@pytest.mark.parametrize("password", ["", "wrong"])
def test_all_session_gates_precede_index_acquisition(
    session_http: tuple[TestClient, ListeningFixture],
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    password: str,
) -> None:
    """Protected routes reject requests before any source check or query validation.

    Args:
        session_http: Independent client/publication fixture.
        monkeypatch: Scoped index-acquisition tripwire.
        path: Each added route.
        password: Missing or incorrect application credential.
    """
    client, fixture = session_http
    probe = Mock(side_effect=AssertionError("unauthenticated history read"))
    monkeypatch.setattr(fixture.runtime, "acquire", probe)
    response = client.get(
        "/lastfm/analytics/sessions" + path, headers={"X-App-Password": password}
    )
    assert response.status_code == 401
    probe.assert_not_called()


def test_complete_session_scope_details_and_page_counts(
    session_http: tuple[TestClient, ListeningFixture],
) -> None:
    """Summary, chart and original-row totals agree without changing authorities.

    Args:
        session_http: Independent credentialed app and source publication.
    """
    client, fixture = session_http
    params = ready_parameters(client)
    before = fixture.service.snapshot()
    source = fixture.source.read_bytes()
    response = client.get(
        "/lastfm/analytics/sessions", params={**params, "order": "plays", "limit": 1}
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    payload = response.json()
    data = payload["data"]
    assert payload["snapshot"] == params["snapshot"]
    assert (
        data["summary"]["selected_plays"] == 8
        and data["summary"]["selected_sessions"] == 3
    )
    assert len(data["items"]) == 1 and data["items"][0]["plays"] == 4
    assert sum(item["plays"] for item in data["buckets"]) == 8
    assert sum(item["sessions"] for item in data["sizes"]) == 3
    first = data["items"][0]["window"]["first_ms"]
    detail = client.get(
        f"/lastfm/analytics/sessions/{first}/records",
        params={**params, "limit": 2, "page": 2},
    )
    assert detail.headers["cache-control"] == "private, no-store"
    assert [row["ordinal"] for row in detail.json()["data"]["records"]["items"]] == [
        4,
        3,
    ]
    assert detail.json()["data"]["records"]["total"] == 4
    assert (
        fixture.source.read_bytes() == source and fixture.service.snapshot() == before
    )


def test_filters_change_inference_and_old_group_ids_do_not_select_partial_groups(
    session_http: tuple[TestClient, ListeningFixture],
) -> None:
    """Filters precede grouping, while minimum plays only filters complete groups.

    Args:
        session_http: Independent credentialed app and source publication.
    """
    client, _ = session_http
    params = ready_parameters(client)
    data = client.get(
        "/lastfm/analytics/sessions",
        params={**params, "gap_minutes": 15, "minimum_plays": 2},
    ).json()["data"]
    assert data["summary"]["selected_sessions"] == 5
    assert (
        data["summary"]["matching_sessions"] == 2
        and data["summary"]["matching_plays"] == 5
    )
    alpha = {
        **params,
        "artist": listening_identity(("Alpha",)),
        "weekday": 0,
        "hour": 12,
    }
    filtered = client.get("/lastfm/analytics/sessions", params=alpha).json()["data"]
    assert filtered["summary"]["selected_plays"] == 2
    first = timestamp("2024-01-01T12:00:00")
    detail = client.get(
        f"/lastfm/analytics/sessions/{first}/records", params=alpha
    ).json()["data"]
    assert [row["artist"] for row in detail["records"]["items"]] == ["Alpha", "Alpha"]
    middle = timestamp("2024-01-01T12:01:00")
    assert (
        client.get(
            f"/lastfm/analytics/sessions/{middle}/records", params=params
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/lastfm/analytics/sessions/{first}/records", params={**params, "hour": 23}
        ).status_code
        == 404
    )


@pytest.mark.parametrize(
    "options",
    [
        {"gap_minutes": 0},
        {"gap_minutes": 241},
        {"gap_minutes": 2.5},
        {"minimum_plays": 0},
        {"minimum_plays": 100000001},
        {"order": "longest"},
        {"page": 0},
        {"limit": 0},
        {"limit": 101},
        {"tz": "bad-zone"},
        {"artist": "not-a-key"},
        {"weekday": 7},
        {"hour": 24},
        {"from": "2025-01-01"},
    ],
)
def test_session_list_rejects_unbounded_or_invalid_options(
    session_http: tuple[TestClient, ListeningFixture],
    options: dict[str, str | int | float],
) -> None:
    """Invalid inference or pagination values never silently change definitions.

    Args:
        session_http: Independent credentialed application.
        options: Deliberately invalid externally supplied values.
    """
    client, _ = session_http
    params = ready_parameters(client)
    assert (
        client.get(
            "/lastfm/analytics/sessions", params={**params, **options}
        ).status_code
        == 422
    )


@pytest.mark.parametrize(
    "path,options",
    [
        ("-1", {}),
        ("4102444800000", {}),
        ("text", {}),
        ("1704110400000", {"gap_minutes": 0}),
        ("1704110400000", {"gap_minutes": 241}),
        ("1704110400000", {"limit": 201}),
        ("1704110400000", {"page": 0}),
    ],
)
def test_session_record_parameters_are_bounded(
    session_http: tuple[TestClient, ListeningFixture],
    path: str,
    options: dict[str, int],
) -> None:
    """Source record IDs and pages stay within explicit safe bounds.

    Args:
        session_http: Credentialed independent application.
        path: Invalid group ID or valid ID with invalid page values.
        options: Deliberately invalid page or inference values.
    """
    client, _ = session_http
    params = ready_parameters(client)
    assert (
        client.get(
            f"/lastfm/analytics/sessions/{path}/records", params={**params, **options}
        ).status_code
        == 422
    )


@pytest.mark.parametrize("suffix", ["", "/1704110400000/records"])
def test_expired_generation_is_rejected_before_reading_session_data(
    session_http: tuple[TestClient, ListeningFixture],
    suffix: str,
) -> None:
    """Both reads stay bound to an explicit complete historical generation.

    Args:
        session_http: Independent credentialed application.
        suffix: Every new data route.
    """
    client, _ = session_http
    params = ready_parameters(client)
    assert (
        client.get(
            "/lastfm/analytics/sessions" + suffix,
            params={**params, "snapshot": "v1-" + "0" * 64},
        ).status_code
        == 409
    )


def test_record_pages_are_chronological_bounded_and_keep_duplicates(
    session_http: tuple[TestClient, ListeningFixture],
) -> None:
    """Large tied groups keep complete counts and return at most 200 rows.

    Args:
        session_http: Independent credentialed app with a deliberate publication.
    """
    client, fixture = session_http
    fixture.publish([scrobble("2024-01-01T12:00:00")] * 205)
    params = ready_parameters(client)
    first = timestamp("2024-01-01T12:00:00")
    one = client.get(
        f"/lastfm/analytics/sessions/{first}/records", params={**params, "limit": 200}
    ).json()["data"]
    two = client.get(
        f"/lastfm/analytics/sessions/{first}/records",
        params={**params, "limit": 200, "page": 2},
    ).json()["data"]
    assert one["session"]["plays"] == one["records"]["total"] == 205
    assert len(one["records"]["items"]) == 200 and len(two["records"]["items"]) == 5
    assert [row["ordinal"] for row in two["records"]["items"]] == list(range(200, 205))
