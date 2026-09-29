"""Actual Queue 3 CLI and HTTP boundaries exercise migrated workflows and choices."""

from collections.abc import Iterator
from datetime import UTC
from datetime import datetime
from datetime import tzinfo
from functools import partial
from threading import Thread
from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from spotipy import Spotify
from typer.testing import CliRunner

from spotify_manager import api
from spotify_manager import main
from spotify_manager.routines import queue_3
from tests.interfaces.test_discovery_slice import _choose
from tests.interfaces.test_discovery_slice import _start
from tests.interfaces.test_discovery_slice import _wait
from tests.interfaces.test_slow_listening_slice import _stop
from tests.interfaces.test_slow_listening_slice import _thread
from tests.interfaces.test_vertical_slices import _http_client
from tests.routines.test_queue_3 import FakeSpotify
from tests.routines.test_queue_3 import raw_release
from tests.routines.test_queue_3 import raw_track


class Queue3Clock(datetime):
    """Keep the real annual-source lookup deterministic across calendar years."""

    @classmethod
    def now(cls, tz: tzinfo | None = None) -> datetime:
        """Return the original test year through the routine's clock boundary.

        Args:
            tz: Requested timezone.

        Returns:
            Fixed September 2026 timestamp in the requested timezone.
        """
        return datetime(2026, 9, 28, tzinfo=UTC).astimezone(tz)


def _spotify() -> FakeSpotify:
    spotify = FakeSpotify()
    current = raw_release("current", "Current", artist_id="artist", release_date="2020")
    following = raw_release(
        "following", "Following", artist_id="artist", release_date="2021"
    )
    source = raw_track("source", "Source", current, artist_id="artist")
    target = raw_track("target", "Target", following, artist_id="artist")
    spotify.playlists["queue3"] = [source]
    spotify.artist_releases["artist"] = [current, following]
    spotify.release_tracks = {"current": [source], "following": [target]}
    return spotify


def _settings() -> SimpleNamespace:
    return SimpleNamespace(the_queue_3_playlist="queue3")


@pytest.fixture
def queue_3_http(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, FakeSpotify]]:
    """Bind real workers to isolated Spotify facts, state, files and a stable year.

    Args:
        monkeypatch: Scoped configuration and external dependency substitutions.

    Yields:
        Real HTTP handlers and mutable Spotify simulation with worker cleanup.
    """
    spotify = _spotify()
    threads: list[Thread] = []
    monkeypatch.setattr(queue_3, "datetime", Queue3Clock)
    monkeypatch.setattr(api, "Settings", _settings)
    monkeypatch.setattr(main, "Settings", _settings)
    monkeypatch.setattr(main, "review_client", Mock(return_value=spotify))
    monkeypatch.setattr(api, "_blast_jobs", {})
    monkeypatch.setattr(api, "Thread", partial(_thread, threads))
    try:
        yield _http_client(monkeypatch, cast(Spotify, spotify)), spotify
    finally:
        _stop(threads)


@pytest.mark.parametrize("preview", [False, True])
def test_http_release_choice_reaches_real_queue_3_review(
    queue_3_http: tuple[TestClient, FakeSpotify],
    preview: bool,
) -> None:
    """HTTP choice validation and workers reach real planning, execution and summary.

    Args:
        queue_3_http: Real HTTP handlers with simulated external services.
        preview: Whether remote playlist effects are suppressed.
    """
    http, spotify = queue_3_http
    job = _start(http, "flush-queue-3", preview)
    waiting = _wait(http, "flush-queue-3", job, "waiting")
    pending = cast(dict[str, object], waiting["queue_3_pending_choice"])
    assert pending["kind"] == "release" and pending["artist"] == "Artist"
    invalid = http.post(
        f"/commands/flush-queue-3-jobs/{job}/choice", json={"choice": "invalid"}
    )
    assert invalid.status_code == 400
    _choose(http, "flush-queue-3", job, "advance")
    completed = _wait(http, "flush-queue-3", job, "completed")
    assert completed["processed"] == 1 and completed["queue_3_changed_releases"] == 1
    assert spotify.mutations == (
        [] if preview else [("add", "target"), ("remove", "source")]
    )


@pytest.mark.parametrize("preview", [False, True])
def test_http_annual_import_executes_without_reviewing_existing_markers(
    queue_3_http: tuple[TestClient, FakeSpotify],
    preview: bool,
) -> None:
    """The dedicated annual command imports source artists without release choices.

    Args:
        queue_3_http: Real HTTP handlers with simulated external services.
        preview: Whether remote playlist effects are suppressed.
    """
    http, spotify = queue_3_http
    album = raw_release("new-album", "New", artist_id="new-artist")
    source = raw_track("new-track", "New Track", album, artist_id="new-artist")
    spotify.playlists["great-2025"] = [source]
    job = _start(http, "import-queue-3-previous-year", preview)
    result = _wait(http, "flush-queue-3", job, "completed")
    assert result["queue_3_annual_only"] is True
    assert result["queue_3_pending_choice"] is None
    assert spotify.mutations == ([] if preview else [("add", "new-track")])
    assert spotify.playlists["queue3"][0]["id"] == "source"


@pytest.mark.parametrize("command", ["flush-queue-3", "import-queue-3-previous-year"])
def test_cli_reaches_real_queue_3_preview_workflow(
    queue_3_http: tuple[TestClient, FakeSpotify],
    command: str,
) -> None:
    """Actual CLI commands reach the migrated use cases and original renderers.

    Args:
        queue_3_http: Scoped CLI configuration and simulated external services.
        command: Public Queue 3 command.
    """
    _http, spotify = queue_3_http
    result = CliRunner().invoke(main.app, [command, "--dry-run"], input="y\n")
    assert result.exit_code == 0, result.output
    assert "Great Discoveries 2025" in result.output
    assert spotify.mutations == []
    if command == "flush-queue-3":
        assert "Target" in result.output and "Would add" in result.output
