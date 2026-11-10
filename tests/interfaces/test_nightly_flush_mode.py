"""Run nightly automation through the real HTTP policy and namespace persistence."""

import json
from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import datetime
from datetime import timedelta
from typing import cast
from unittest.mock import AsyncMock
from urllib.parse import urlsplit
from urllib.request import Request
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from spotipy.exceptions import SpotifyException

from spotify_manager.application.automation_run import nightly_refresh
from spotify_manager.application.automation_values import DURABLE_ARTIFACT_FILENAMES
from spotify_manager.application.automation_values import JOBS
from spotify_manager.application.ports.spotify_client import SpotifyClient
from spotify_manager.bootstrap import flush_mode as composition
from spotify_manager.domain.flush_mode import FlushControl
from spotify_manager.infrastructure.automation_http import SpaceHttpClient
from tests.infrastructure.test_automation_http_contracts import Response
from tests.interfaces.test_flush_mode_slice import _configuration
from tests.interfaces.test_vertical_slices import _http_client
from tests.support.runtime_resources import MessageList


@dataclass
class MaintenanceLoopback:
    """Route real authenticated-client requests to an isolated ASGI application.

    Args:
        http: Real test HTTP application with local shared state.
        paths: Complete maintenance request sequence.
        observations: Successful and failed POST responses from the real policy.
        waits: Retry durations without wall-clock delays.
    """

    http: TestClient
    paths: list[tuple[str, str]] = field(default_factory=list)
    observations: list[dict[str, object]] = field(default_factory=list)
    waits: list[float] = field(default_factory=list)

    def open(self, request: Request, *, timeout: int) -> Response:
        """Open one real policy request or independent already-current file status.

        Args:
            request: Prepared request from the actual urllib adapter.
            timeout: Existing bounded request timeout.

        Returns:
            Context-managed response with actual API status and body.
        """
        path = urlsplit(request.full_url).path
        self.paths.append((request.get_method(), path))
        if path == "/library-mirrors/status":
            return Response(json.dumps(_fresh_files()).encode())
        response = self.http.request(request.get_method(), path)
        if path == "/flush-mode/check":
            self.observations.append(response.json())
        return Response(response.content, response.status_code)

    def now(self) -> datetime:
        """Observe time for real request and deadline ownership.

        Returns:
            Current aware UTC instant.
        """
        return datetime.now(UTC)

    def sleep(self, seconds: float) -> None:
        """Record maintenance waits without blocking the integration test.

        Args:
            seconds: Bounded retry duration.
        """
        self.waits.append(seconds)


def _fresh_files() -> dict[str, object]:
    files = []
    for filename in DURABLE_ARTIFACT_FILENAMES:
        files.append(
            {
                "filename": filename,
                "exists": True,
                "updated_at": "2026-11-09T00:00:00+00:00",
            }
        )
    return {"files": files}


def _run(transport: MaintenanceLoopback) -> None:
    output = MessageList([])
    client = SpaceHttpClient(
        "https://loopback.test/",
        "test-hf",
        "test-automation",
        transport.now() + timedelta(minutes=5),
        transport,
        transport,
        transport,
        output,
    )
    assert (
        nightly_refresh(
            client,
            JOBS,
            datetime(2026, 11, 8, tzinfo=UTC),
            ZoneInfo("Europe/Berlin"),
            transport,
            output,
        )
        == 0
    )


@pytest.mark.parametrize("control", ["automatic", "on", "off"])
def test_repeated_nightly_checks_preserve_override_and_hysteresis(
    monkeypatch: pytest.MonkeyPatch,
    control: FlushControl,
) -> None:
    """Current files cannot suppress observations, failures, recovery or exit.

    Args:
        monkeypatch: Isolated configured playlist references.
        control: Persistent Automatic, Force On or Force Off selection.
    """
    monkeypatch.setattr(composition, "Settings", _configuration)
    spotify = AsyncMock()
    spotify.get.side_effect = [
        {"total": 2399},
        {"total": 1199},
        {"total": 2400},
        {"total": 900},
        {"total": 1300},
        {"total": 950},
        SpotifyException(503, -1, "offline"),
        {"total": 1200},
        {"total": 900},
    ]
    with _http_client(monkeypatch, cast(SpotifyClient, spotify)) as http:
        assert (
            http.put("/flush-mode/control", json={"control": control}).status_code
            == 200
        )
        transport = MaintenanceLoopback(http)
        for automatic in (False, True, True, False):
            _run(transport)
            state = composition.flush_mode_state().load()
            assert state.control == control and state.automatic_active == automatic
            assert state.active == (
                automatic if control == "automatic" else control == "on"
            )
        failed, recovered = transport.observations[-2:]
        assert failed["error"] and failed["queue_tracks"] == 1300
        assert failed["checked_at"] == transport.observations[-3]["checked_at"]
        assert recovered["error"] is None and recovered["queue_tracks"] == 1200
        assert transport.waits == [20]
        assert transport.paths.count(("POST", "/flush-mode/check")) == 5
        assert not any(path.startswith("/commands/") for _, path in transport.paths)
    assert spotify.get.await_count == 9
