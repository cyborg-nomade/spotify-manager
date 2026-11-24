"""Gated cached quilts, exact selection scope and protected immutable image bytes."""

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
from spotify_manager.application import listening_covers
from spotify_manager.application.listening_covers import ListeningCoverEnrichment
from spotify_manager.domain.listening_cover_values import CoverFetchResult
from spotify_manager.domain.listening_values import RankedEntity
from spotify_manager.infrastructure.listening.cover_cache import AlbumCoverCache
from spotify_manager.interfaces.http.listening import router as history_router
from spotify_manager.interfaces.http.listening_quilt import router
from tests.interfaces.test_listening_slice import ready_parameters
from tests.support.listening import ListeningFixture
from tests.support.listening import listening_fixture
from tests.support.listening import sample_history
from tests.support.listening_covers import FixtureCoverSource
from tests.support.listening_covers import cover_result


@asynccontextmanager
async def cover_lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Drain fixture cover work before releasing the independent history runtime.

    Args:
        app: Fixture application owning only synthetic resources.

    Returns:
        An owned application lifetime that drains cover work before shutdown.
    """
    try:
        yield
    finally:
        await app.state.listening_covers.close()
        await app.state.listening.close()


@pytest.fixture
def cover_http(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[
    tuple[TestClient, ListeningFixture, ListeningCoverEnrichment, FixtureCoverSource]
]:
    """Serve real protected routes over synthetic independently published history.

    Args:
        tmp_path: Isolated test-owned directory for derived metadata and history.
        monkeypatch: Scoped replacements for timing and concrete integration boundaries.

    Returns:
        Owned protected client, history, cache and provider resources.
    """
    monkeypatch.setattr(listening_covers, "REQUEST_INTERVAL", 0)
    fixture = listening_fixture(tmp_path)
    fixture.publish(sample_history())
    source = FixtureCoverSource()
    stage = ListeningCoverEnrichment(AlbumCoverCache(tmp_path / "covers"), source)
    app = FastAPI(lifespan=cover_lifespan)
    app.state.listening = fixture.runtime
    app.state.listening_covers = stage
    app.include_router(history_router)
    app.include_router(router)
    app.add_middleware(PasswordMiddleware, password="cover-test-password")
    with TestClient(app) as client:
        client.headers["X-App-Password"] = "cover-test-password"
        yield client, fixture, stage, source


def finished(client: TestClient) -> dict[str, object]:
    """Wait for one bounded no-network fixture batch.

    Args:
        client: Protected fixture HTTP client.

    Returns:
        Final lookup progress after the controlled batch stops.
    """
    deadline = monotonic() + 10
    while monotonic() < deadline:
        status = client.get("/lastfm/analytics/quilt/status").json()
        if status["state"] not in ("running", "cancelling"):
            return status
        sleep(0.001)
    raise AssertionError("Fixture cover batch did not finish.")


def test_cached_reads_and_images_do_not_fetch_or_change_canonical_data(
    cover_http: tuple[
        TestClient, ListeningFixture, ListeningCoverEnrichment, FixtureCoverSource
    ],
) -> None:
    """GETs stay local; an explicit batch binds complete metadata and image bytes.

    Args:
        cover_http: Protected client, published history, cover stage and offline provider.
    """
    client, fixture, stage, source = cover_http
    params = ready_parameters(client)
    status = client.get("/lastfm/analytics/quilt/status")
    assert status.headers["Cache-Control"] == "private, no-store"
    selected = {**params, "metadata_snapshot": status.json()["metadata_snapshot"]}
    response = client.get("/lastfm/analytics/quilt", params=selected)
    assert (
        response.status_code == 200
        and response.headers["Cache-Control"] == "private, no-store"
    )
    data = response.json()["data"]
    assert data["coverage"]["plays"] == 7 and data["coverage"]["artwork_albums"] == 0
    assert source.names == []
    revision = fixture.service.snapshot().revision
    assert (
        client.post(
            "/lastfm/analytics/quilt/refresh", params={**params, "limit": 1}
        ).status_code
        == 200
    )
    status = finished(client)
    assert status["completed"] == 1 and source.names == ["Record"]
    current = {**params, "metadata_snapshot": str(status["metadata_snapshot"])}
    data = client.get("/lastfm/analytics/quilt", params=current).json()["data"]
    assert data["coverage"]["artwork_plays"] == 4
    key = data["items"][0]["album"]["key"]
    image = client.get(
        "/lastfm/analytics/quilt/images/" + key,
        params={"metadata_snapshot": status["metadata_snapshot"]},
    )
    assert image.status_code == 200 and image.headers["content-type"] == "image/jpeg"
    assert (
        image.headers["Cache-Control"] == "private, no-store"
        and image.headers["X-Content-Type-Options"] == "nosniff"
    )
    assert image.content == stage.cache.current().images[0].content
    assert (
        client.get("/lastfm/analytics/quilt", params=selected).json()["data"][
            "coverage"
        ]["artwork_albums"]
        == 0
    )
    assert fixture.service.snapshot().revision == revision


def test_explicit_lookup_respects_displayed_search_and_invalid_bounds(
    cover_http: tuple[
        TestClient, ListeningFixture, ListeningCoverEnrichment, FixtureCoverSource
    ],
) -> None:
    """Search and size are captured before starting a bounded batch.

    Args:
        cover_http: Protected client, published history, cover stage and offline provider.
    """
    client, _fixture, _stage, source = cover_http
    params = ready_parameters(client)
    assert (
        client.post(
            "/lastfm/analytics/quilt/refresh",
            params={**params, "q": "Unknown", "size": 9},
        ).status_code
        == 200
    )
    assert finished(client)["completed"] == 0 and not source.names
    assert (
        client.post(
            "/lastfm/analytics/quilt/refresh", params={**params, "limit": 11}
        ).status_code
        == 422
    )
    assert client.post("/lastfm/analytics/quilt/cancel").status_code == 200


@pytest.mark.parametrize(
    "extra",
    [{"size": 100}, {"size": 10}, {"q": "x" * 101}, {"metadata_snapshot": "bad"}],
)
def test_unbounded_or_invalid_view_queries_are_rejected(
    cover_http: tuple[
        TestClient, ListeningFixture, ListeningCoverEnrichment, FixtureCoverSource
    ],
    extra: dict[str, object],
) -> None:
    """Unbounded or invalid view queries are rejected.

    Args:
        cover_http: Protected client, published history, cover stage and offline provider.
        extra: Invalid query options applied to a bounded fixture request.
    """
    client, _fixture, stage, _source = cover_http
    params = {
        **ready_parameters(client),
        "metadata_snapshot": stage.cache.current().snapshot,
        **extra,
    }
    assert client.get("/lastfm/analytics/quilt", params=params).status_code == 422


def test_expired_cover_version_is_independent_of_history_and_images(
    cover_http: tuple[
        TestClient, ListeningFixture, ListeningCoverEnrichment, FixtureCoverSource
    ],
) -> None:
    """Both analytical and byte reads report the precise metadata conflict.

    Args:
        cover_http: Protected client, published history, cover stage and offline provider.
    """
    client, _fixture, stage, _source = cover_http
    params = ready_parameters(client)
    old = stage.cache.current().snapshot
    stage.cache.write(cover_result())
    stage.cache.write(cover_result("Another"))
    response = client.get(
        "/lastfm/analytics/quilt", params={**params, "metadata_snapshot": old}
    )
    assert (
        response.status_code == 409
        and response.headers["X-Listening-Conflict"] == "covers"
    )
    image = client.get(
        "/lastfm/analytics/quilt/images/" + "0" * 64, params={"metadata_snapshot": old}
    )
    assert (
        image.status_code == 409 and image.headers["X-Listening-Conflict"] == "covers"
    )
    assert client.get("/lastfm/analytics/overview", params=params).status_code == 200
    assert (
        client.get(
            "/lastfm/analytics/quilt/images/" + "0" * 64,
            params={"metadata_snapshot": stage.cache.current().snapshot},
        ).status_code
        == 404
    )


@pytest.mark.parametrize(
    "path,method",
    [
        ("/status", "GET"),
        ("", "GET"),
        ("/images/" + "0" * 64, "GET"),
        ("/refresh", "POST"),
        ("/prefetch", "POST"),
        ("/cancel", "POST"),
    ],
)
def test_all_quilt_routes_reject_missing_and_wrong_credentials(
    cover_http: tuple[
        TestClient, ListeningFixture, ListeningCoverEnrichment, FixtureCoverSource
    ],
    path: str,
    method: str,
) -> None:
    """All quilt routes reject missing and wrong credentials.

    Args:
        cover_http: Protected client, published history, cover stage and offline provider.
        path: Fixed route suffix under the protected quilt namespace.
        method: HTTP method used to verify the protected route.
    """
    client, _fixture, _stage, source = cover_http
    client.headers.pop("X-App-Password")
    assert client.request(method, "/lastfm/analytics/quilt" + path).status_code == 401
    assert (
        client.request(
            method,
            "/lastfm/analytics/quilt" + path,
            headers={"X-App-Password": "wrong"},
        ).status_code
        == 401
    )
    assert source.names == []


def test_source_unavailability_does_not_block_historical_views(
    cover_http: tuple[
        TestClient, ListeningFixture, ListeningCoverEnrichment, FixtureCoverSource
    ],
) -> None:
    """Source unavailability does not block historical views.

    Args:
        cover_http: Protected client, published history, cover stage and offline provider.
    """
    client, _fixture, _stage, source = cover_http
    params = ready_parameters(client)
    source.configured = False
    assert (
        client.post("/lastfm/analytics/quilt/refresh", params=params).status_code == 503
    )
    assert client.get("/lastfm/analytics/overview", params=params).status_code == 200


class FixtureLastFmCovers:
    """Return one controlled cover and record the selected album credits."""

    available = True

    def __init__(self) -> None:
        """Start with no submitted credits."""
        self.artists: list[str] = []

    async def fetch(self, album: RankedEntity) -> CoverFetchResult | None:
        """Return synthetic cover evidence for Beta only."""
        self.artists.append(album.artist)
        if album.artist != "Beta":
            return None
        return cover_result(album.name, album.artist)


def test_prefetch_skips_covers_and_recent_misses_without_using_the_archive(
    cover_http: tuple[
        TestClient, ListeningFixture, ListeningCoverEnrichment, FixtureCoverSource
    ],
) -> None:
    """Only missing visible artwork is sent to Last.fm during a prefetch."""
    client, _fixture, stage, archive = cover_http
    quick = FixtureLastFmCovers()
    stage.quick_source = quick
    stage.cache.write(cover_result())
    params = ready_parameters(client)
    path = "/lastfm/analytics/quilt"
    response = client.post(path + "/prefetch", params={**params, "q": "Alpha"})
    assert response.status_code == 200 and response.json()["state"] == "idle"
    assert quick.artists == []
    assert client.post(path + "/prefetch", params=params).status_code == 200
    status = finished(client)
    assert (status["total"], status["completed"]) == (2, 1)
    assert quick.artists == ["Beta", "Béta"] and archive.names == []
    assert client.post(path + "/prefetch", params=params).json() == status
    assert quick.artists == ["Beta", "Béta"]
    assert client.post(path + "/refresh", params={**params, "q": "Béta"}).is_success
    assert finished(client)["completed"] == 1
    assert archive.names == ["Record"]
