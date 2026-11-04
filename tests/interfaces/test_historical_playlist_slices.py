"""Actual historical CLI/HTTP commands with isolated external observations."""

import json
from collections.abc import Iterator
from datetime import UTC
from datetime import datetime
from datetime import tzinfo
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from spotify_manager import main
from spotify_manager.application.ports.spotify_client import SpotifyClient as Spotify
from spotify_manager.interfaces.http import jobs as http_jobs
from spotify_manager.routines import blast_from_past as blast
from spotify_manager.routines import daily_mind_radio as radio
from tests.interfaces.test_discovery_slice import _wait
from tests.interfaces.test_slow_listening_slice import _stop
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
    _history()
    response = MagicMock()
    response.__enter__.return_value = response
    response.read.return_value = b"0"
    response.headers = {"Date": "Wed, 22 Jul 2026 13:00:52 GMT"}
    monkeypatch.setattr(blast, "urlopen", Mock(return_value=response))
    monkeypatch.setattr(blast, "datetime", HistoricalClock)
    monkeypatch.setattr(radio, "datetime", HistoricalClock)
    monkeypatch.setattr(http_jobs, "Settings", _settings)
    monkeypatch.setattr(main, "Settings", _settings)
    monkeypatch.setattr(main, "_native_client", AsyncMock(return_value=spotify))
    monkeypatch.setattr(http_jobs, "_blast_jobs", {})
    command = "blast-from-the-past" if kind == "blast" else "daily-mind-radio"
    with _http_client(monkeypatch, cast(Spotify, spotify)) as http:
        try:
            yield (http, spotify, command)
        finally:
            _stop()


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


def _manual_candidates(spotify: SimulatedSpotify, count: int = 3) -> None:
    spotify.search_results.clear()
    spotify.search_results["Artist Song Album"] = [
        spotify_track(
            f"manual-{index}",
            f"Different {index}",
            "Other artist",
            "Other album",
            index,
        )
        for index in range(count)
    ]
    spotify.liked_ids = {"manual-1"}


def _start_manual(http: TestClient, command: str, preview: bool = True) -> str:
    params: dict[str, bool | int] = {"dry_run": preview}
    if command == "blast-from-the-past":
        params["count"] = 1
    response = http.post(f"/commands/{command}", params=params)
    assert response.status_code == 202, response.text
    return str(response.json()["job_id"])


def _pending_match(http: TestClient, command: str, job: str) -> dict[str, object]:
    result = _wait(http, command, job, "waiting")
    return cast(dict[str, object], result["track_match_pending_choice"])


@pytest.mark.parametrize("preview", [False, True])
def test_http_manual_selection_preserves_search_order_preview_and_duplicates(
    historical_http: tuple[TestClient, SimulatedSpotify, str], preview: bool
) -> None:
    """Exercise explicit selection through the actual routes, workers and use cases.

    Args:
        historical_http: Real commands with isolated external observations.
        preview: Whether accepted changes must remain a preview.
    """
    http, spotify, command = historical_http
    _manual_candidates(spotify)
    job = _start_manual(http, command, preview)
    for _index in range(1 if command == "blast-from-the-past" else 2):
        pending = _pending_match(http, command, job)
        candidates = cast(list[dict[str, object]], pending["candidates"])
        assert [item["spotify_id"] for item in candidates] == [
            "manual-0",
            "manual-1",
            "manual-2",
        ]
        assert candidates[1]["artists"] == ["Other artist"]
        assert candidates[1]["url"] == "https://open.spotify.com/track/manual-1"
        response = http.post(
            f"/commands/{command}-jobs/{job}/choice",
            json={"request_id": pending["request_id"], "choice": "manual-1"},
        )
        assert response.status_code == 200, response.text
    result = _wait(http, command, job, "completed")
    assert result["added"] == 1
    assert len(spotify.posts) == int(not preview)
    selections = cast(list[dict[str, object]], result["selections"])
    assert selections[0]["liked"] is True
    assert selections[0]["qualifying_matches"] == 0
    assert [item["action"] for item in selections] == (
        ["added"]
        if command == "blast-from-the-past"
        else ["added", "duplicate selection"]
    )


@pytest.mark.parametrize("count", [0, 10])
def test_http_manual_rejection_handles_empty_and_ten_results(
    historical_http: tuple[TestClient, SimulatedSpotify, str], count: int
) -> None:
    """Complete the batch after rejecting empty or populated search results.

    Args:
        historical_http: Real commands with isolated external observations.
        count: Number of search results returned by the simulated catalog.
    """
    http, spotify, command = historical_http
    _manual_candidates(spotify, count)
    job = _start_manual(http, command)
    for _index in range(1 if command == "blast-from-the-past" else 2):
        pending = _pending_match(http, command, job)
        assert len(cast(list[object], pending["candidates"])) == count
        response = http.post(
            f"/commands/{command}-jobs/{job}/choice",
            json={"request_id": pending["request_id"], "choice": ""},
        )
        assert response.status_code == 200
    result = _wait(http, command, job, "completed")
    assert result["added"] == 0
    assert spotify.posts == []


def test_http_matching_reconnect_validation_and_cancellation(
    historical_http: tuple[TestClient, SimulatedSpotify, str],
) -> None:
    """Reconnect to a pending choice and reject stale, invalid and cancelled requests.

    Args:
        historical_http: Real commands with isolated external observations.
    """
    http, spotify, command = historical_http
    _manual_candidates(spotify)
    job = _start_manual(http, command, preview=False)
    pending = _pending_match(http, command, job)
    active = http.get(f"/commands/{command}-jobs").json()
    assert active[0]["track_match_pending_choice"] == pending
    path = f"/commands/{command}-jobs/{job}"
    assert (
        http.post(
            path + "/choice", json={"request_id": "stale", "choice": "manual-0"}
        ).status_code
        == 409
    )
    assert (
        http.post(
            path + "/choice",
            json={"request_id": pending["request_id"], "choice": "unoffered"},
        ).status_code
        == 400
    )
    other = (
        "daily-mind-radio"
        if command == "blast-from-the-past"
        else "blast-from-the-past"
    )
    assert (
        http.post(
            f"/commands/{other}-jobs/{job}/choice",
            json={"request_id": pending["request_id"], "choice": "manual-0"},
        ).status_code
        == 404
    )
    assert http.post(path + "/cancel").status_code == 200
    result = _wait(http, command, job, "cancelled")
    assert result["track_match_pending_choice"] is None
    assert (
        http.post(
            path + "/choice",
            json={"request_id": pending["request_id"], "choice": "manual-0"},
        ).status_code
        == 409
    )
    assert spotify.posts == []


@pytest.mark.parametrize(
    "answer,expected", [("2", "would add 1"), ("n", "would add 0"), ("q", "cancelled")]
)
def test_cli_manual_matching_selection_rejection_and_cancellation(
    historical_http: tuple[TestClient, SimulatedSpotify, str],
    answer: str,
    expected: str,
) -> None:
    """Exercise real terminal prompts without allowing preview playlist writes.

    Args:
        historical_http: Real commands with isolated external observations.
        answer: Scripted explicit decision.
        expected: Expected terminal completion or cancellation text.
    """
    _http, spotify, command = historical_http
    _manual_candidates(spotify)
    arguments = [command, "--dry-run"]
    if command == "blast-from-the-past":
        arguments.extend(["--count", "1"])
    result = CliRunner().invoke(main.app, arguments, input=f"{answer}\n{answer}\n")
    assert result.exit_code == (1 if answer == "q" else 0), result.output
    assert "Choose a Spotify match" in result.output
    assert "Other artist" in result.output
    assert expected in result.output.lower()
    assert spotify.posts == []
