"""Actual historical CLI/HTTP commands with isolated external observations."""

import json
from collections.abc import Iterator
from datetime import UTC
from datetime import datetime
from datetime import tzinfo
from functools import partial
from threading import Thread
from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from spotipy import Spotify
from typer.testing import CliRunner

from spotify_manager import api
from spotify_manager import main
from spotify_manager.routines import blast_from_past as blast
from spotify_manager.routines import daily_mind_radio as radio
from tests.interfaces.test_discovery_slice import _wait
from tests.interfaces.test_slow_listening_slice import _stop
from tests.interfaces.test_slow_listening_slice import _thread
from tests.interfaces.test_vertical_slices import _http_client
from tests.routines.test_blast_from_past import FakeSpotify as BlastSpotify
from tests.routines.test_daily_mind_radio import FakeSpotify as RadioSpotify
from tests.routines.test_daily_mind_radio import export_scrobble
from tests.routines.test_daily_mind_radio import spotify_track


type SimulatedSpotify = BlastSpotify | RadioSpotify


class HistoricalClock(datetime):
    """Keep real calendar-dependent history selection deterministic."""

    @classmethod
    def now(cls, tz: tzinfo | None = None) -> datetime:
        """Return the fixed local selection date.

        Args:
            tz: Requested timezone.

        Returns:
            Fixed timestamp interpreted in the requested timezone.
        """
        return datetime(2026, 7, 22, 12, tzinfo=UTC).astimezone(tz)


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        blast_from_the_past_playlist="blast", daily_mind_radio_playlist="daily"
    )


def _spotify(kind: str) -> SimulatedSpotify:
    spotify = BlastSpotify() if kind == "blast" else RadioSpotify()
    query = blast.spotify_search_query(blast.Scrobble("Song", "Artist", "Album", 1))
    spotify.search_results[query] = [
        spotify_track("unliked", "Song", "Artist", "Album", 100),
        spotify_track("liked", "Song - Remastered", "Artist", "Different", 1),
    ]
    spotify.liked_ids = {"liked"}
    return spotify


def _history() -> None:
    plays = [
        export_scrobble(datetime(2025, 7, 22).date(), "Song"),
        export_scrobble(datetime(2015, 7, 22).date(), "Song"),
    ]
    blast.DEFAULT_SCROBBLES_PATH.write_text(json.dumps({"scrobbles": plays}))


@pytest.fixture(params=["blast", "radio"])
def historical_http(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[TestClient, SimulatedSpotify, str]]:
    """Bind actual jobs to deterministic history, randomness, clocks and fake Spotify.

    Args:
        request: Selected historical routine.
        monkeypatch: Scoped dependency substitutions.

    Yields:
        Real HTTP handlers, simulated Spotify and public command name.
    """
    kind = str(request.param)
    spotify = _spotify(kind)
    threads: list[Thread] = []
    _history()
    response = MagicMock()
    response.__enter__.return_value = response
    response.read.return_value = b"0"
    response.headers = {"Date": "Wed, 22 Jul 2026 13:00:52 GMT"}
    monkeypatch.setattr(blast, "urlopen", Mock(return_value=response))
    monkeypatch.setattr(blast, "datetime", HistoricalClock)
    monkeypatch.setattr(radio, "datetime", HistoricalClock)
    monkeypatch.setattr(api, "Settings", _settings)
    monkeypatch.setattr(main, "Settings", _settings)
    monkeypatch.setattr(main, "client", Mock(return_value=spotify))
    monkeypatch.setattr(api, "_blast_jobs", {})
    monkeypatch.setattr(api, "Thread", partial(_thread, threads))
    command = "blast-from-the-past" if kind == "blast" else "daily-mind-radio"
    try:
        yield _http_client(monkeypatch, cast(Spotify, spotify)), spotify, command
    finally:
        _stop(threads)


@pytest.mark.parametrize("preview", [False, True])
def test_http_historical_jobs_execute_selection_and_liked_override(
    historical_http: tuple[TestClient, SimulatedSpotify, str], preview: bool
) -> None:
    """Real jobs preserve liked overrides, duplicate selections and preview summaries.

    Args:
        historical_http: Actual HTTP handlers with isolated external dependencies.
        preview: Suppress accepted playlist mutations.
    """
    http, spotify, command = historical_http
    params: dict[str, bool | int] = {"dry_run": preview}
    if command == "blast-from-the-past":
        params["count"] = 1
    response = http.post(f"/commands/{command}", params=params)
    assert response.status_code == 202, response.text
    result = _wait(http, command, str(response.json()["job_id"]), "completed")
    assert result["added"] == 1
    assert result["playlist_length_before"] == 0
    assert result["playlist_length_after"] == int(not preview)
    target = "blast" if command == "blast-from-the-past" else "daily"
    assert spotify.posts == (
        []
        if preview
        else [(f"playlists/{target}/items", {"uris": ["spotify:track:liked"]})]
    )
    selections = cast(list[dict[str, object]], result["selections"])
    assert len(selections) == (1 if target == "blast" else 2)
    assert selections[0]["liked"] is True
    assert selections[0]["action"] == "added"
    if target == "daily":
        assert selections[1]["action"] == "duplicate selection"


def test_cli_historical_preview_executes_real_selection(
    historical_http: tuple[TestClient, SimulatedSpotify, str],
) -> None:
    """The actual CLI renders qualified matches while preview suppresses appends.

    Args:
        historical_http: Scoped CLI dependencies and deterministic observations.
    """
    _http, spotify, command = historical_http
    arguments = [command, "--dry-run"]
    if command == "blast-from-the-past":
        arguments.extend(["--count", "1"])
    result = CliRunner().invoke(main.app, arguments)
    assert result.exit_code == 0, result.output
    assert "Random.org timestamp" in result.output
    assert "would add 1" in result.output.lower()
    assert spotify.posts == []
