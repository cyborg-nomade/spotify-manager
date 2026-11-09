"""Authenticated history downloads preserve stored bytes and release their files."""

from asyncio import CancelledError
from collections.abc import Iterator
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock
from unittest.mock import Mock

import pytest
from fastapi.responses import FileResponse
from fastapi.testclient import TestClient
from starlette.types import Receive
from starlette.types import Scope
from starlette.types import Send

from spotify_manager import api
from spotify_manager._auth import PasswordMiddleware
from spotify_manager.core.library_data.models import LibraryDataConfigurationError
from spotify_manager.core.library_data.models import LibraryDataConflictError
from spotify_manager.core.library_data.models import LibraryDataDocumentError
from spotify_manager.core.library_data.models import LibraryDataIntegrityError
from spotify_manager.core.library_data.models import payload_sha256
from spotify_manager.interfaces.http.handlers import history_download
from tests.support.scrobble_downloads import HISTORY
from tests.support.scrobble_downloads import DownloadFixture
from tests.support.scrobble_downloads import download_fixture
from tests.support.scrobble_downloads import publish_history


@pytest.fixture
def download_http(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[TestClient, DownloadFixture]]:
    """Use the actual route, deployment gate and application with local resources.

    Args:
        tmp_path: Test-owned artifact and spool directories.
        monkeypatch: Scoped bootstrap resource replacement.

    Yields:
        Authenticated HTTP client and real isolated artifact resources.
    """
    fixture = download_fixture(tmp_path)
    monkeypatch.setattr(
        history_download, "scrobble_downloads", Mock(return_value=fixture.files)
    )
    protected = PasswordMiddleware(api.app, "download-password")
    with TestClient(protected) as http:
        http.headers["X-App-Password"] = "download-password"
        yield http, fixture


def test_download_delivers_original_bytes_headers_and_cleans_up(
    download_http: tuple[TestClient, DownloadFixture],
) -> None:
    """No JSON rebuilding, working-file fallback, publication or spool leak occurs.

    Args:
        download_http: Actual authenticated route and durable storage.
    """
    http, fixture = download_http
    publish_history(fixture)
    revision = fixture.service.snapshot().revision
    fixture.working.write_bytes(b"a sync is editing this working file")
    response = http.get("/scrobble-history/download")
    assert response.status_code == 200 and response.content == HISTORY
    assert response.headers["content-type"] == "application/json"
    assert response.headers["content-length"] == str(len(HISTORY))
    assert response.headers["etag"] == f'"{payload_sha256(HISTORY)}"'
    assert response.headers["cache-control"] == "no-store"
    assert (
        response.headers["content-disposition"]
        == f'attachment; filename="{fixture.working.name}"'
    )
    assert fixture.service.snapshot().revision == revision
    assert not list(fixture.spool.iterdir())
    assert fixture.working.read_bytes() == b"a sync is editing this working file"


def test_download_requires_authentication_before_acquiring_a_snapshot(
    download_http: tuple[TestClient, DownloadFixture], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Private history is protected by the deployment's existing password gate.

    Args:
        download_http: Actual route protected by the normal middleware.
        monkeypatch: Scoped acquisition probe.
    """
    http, _fixture = download_http
    factory = Mock(side_effect=AssertionError("unauthenticated acquisition"))
    monkeypatch.setattr(history_download, "scrobble_downloads", factory)
    http.headers.pop("X-App-Password")
    assert http.get("/scrobble-history/download").status_code == 401
    assert (
        http.get(
            "/scrobble-history/download", headers={"X-App-Password": "wrong"}
        ).status_code
        == 401
    )
    factory.assert_not_called()


def test_missing_stored_history_returns_a_clear_error(
    download_http: tuple[TestClient, DownloadFixture],
) -> None:
    """A working-only or absent export is not mistaken for durable history.

    Args:
        download_http: Actual route and empty canonical store.
    """
    http, fixture = download_http
    fixture.working.write_bytes(HISTORY)
    response = http.get("/scrobble-history/download")
    assert (
        response.status_code == 404
        and "Sync history first" in response.json()["detail"]
    )
    assert not list(fixture.spool.iterdir())


@pytest.mark.parametrize(
    "error,status",
    [
        (LibraryDataConflictError("publication raced"), 409),
        (LibraryDataDocumentError("invalid manifest"), 502),
        (LibraryDataIntegrityError("wrong checksum"), 502),
        (LibraryDataConfigurationError("storage offline"), 503),
        (OSError("no temporary storage"), 503),
    ],
)
def test_storage_errors_cannot_become_successful_attachments(
    download_http: tuple[TestClient, DownloadFixture],
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    status: int,
) -> None:
    """Specific storage failures remain explicit JSON errors.

    Args:
        download_http: Actual authenticated HTTP lifecycle.
        monkeypatch: Scoped bootstrap failure injection.
        error: Specific configuration, integrity, conflict or temporary-file failure.
        status: Expected public HTTP status.
    """
    http, _fixture = download_http
    monkeypatch.setattr(history_download, "scrobble_downloads", Mock(side_effect=error))
    response = http.get("/scrobble-history/download")
    assert response.status_code == status
    assert "content-disposition" not in response.headers


@pytest.mark.parametrize("error", [OSError("client disconnected"), CancelledError()])
async def test_failed_or_cancelled_response_delivery_always_releases_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: OSError | CancelledError
) -> None:
    """Response ownership covers exceptions and task cancellation during sending.

    Args:
        tmp_path: Independent spool and durable artifact directories.
        monkeypatch: Scoped framework delivery failure.
        error: Disconnect or cancellation after preparing the verified file.
    """
    fixture = download_fixture(tmp_path)
    publish_history(fixture)
    snapshot = fixture.files.prepare()
    assert snapshot is not None
    response = history_download.ScrobbleHistoryResponse(snapshot)
    monkeypatch.setattr(FileResponse, "__call__", AsyncMock(side_effect=error))
    with pytest.raises(type(error)):
        await response(
            cast(Scope, {}), cast(Receive, AsyncMock()), cast(Send, AsyncMock())
        )
    assert not snapshot.path.exists() and not list(fixture.spool.iterdir())
