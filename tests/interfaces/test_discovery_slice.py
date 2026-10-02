"""Real New Kids and Queue 2 CLI/HTTP choices through migrated review workflows."""

import json
from collections.abc import Iterator
from functools import partial
from threading import Thread
from time import monotonic
from time import sleep
from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from spotipy import Spotify
from typer.testing import CliRunner

from spotify_manager import api
from spotify_manager import main
from spotify_manager.routines import new_kids
from tests.interfaces.test_slow_listening_slice import _stop
from tests.interfaces.test_slow_listening_slice import _thread
from tests.interfaces.test_vertical_slices import _http_client
from tests.routines.test_new_kids import FakeSpotify
from tests.routines.test_new_kids import raw_release
from tests.routines.test_new_kids import raw_track
from tests.routines.test_scrobble_history import FakeLastFm


def _spotify() -> FakeSpotify:
    spotify = FakeSpotify()
    current = raw_release("current", "Current", total_tracks=1)
    following = raw_release("following", "Following", total_tracks=1)
    source = raw_track("source", "Source", current)
    target = raw_track("target", "Target", following)
    spotify.playlists["new"] = [source]
    spotify.artist_releases["artist"] = [current, following]
    spotify.release_tracks = {"current": [source], "following": [target]}
    return spotify


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        new_kids_on_the_block_playlist="new",
        the_queue_2_playlist="queue",
        great_discoveries_2026_playlist="great",
        unlucky_ones_playlist="unlucky",
        discography_newfoundland_playlist="newfoundland",
        lastfm_api_key="test-key",
        lastfm_username="test-user",
    )


@pytest.fixture
def discovery_http(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, FakeSpotify]]:
    """Bind real workers and history refresh to isolated simulated external services.

    Args:
        monkeypatch: Scoped settings and dependency overrides.

    Yields:
        Real HTTP client and mutable Spotify simulation, with worker cleanup.
    """
    spotify = _spotify()
    threads: list[Thread] = []
    history = [{"artist": "Unrelated", "track": "Old", "album": "Old", "date": 1000}]
    new_kids.DEFAULT_SCROBBLES_PATH.write_text(
        json.dumps({"username": "test-user", "scrobbles": history})
    )
    monkeypatch.setattr(api, "Settings", _settings)
    monkeypatch.setattr(main, "Settings", _settings)
    monkeypatch.setattr(main, "review_client", Mock(return_value=spotify))
    monkeypatch.setattr(api, "LastFmClient", Mock(return_value=FakeLastFm(())))
    monkeypatch.setattr(main, "LastFmClient", Mock(return_value=FakeLastFm(())))
    monkeypatch.setattr(api, "_blast_jobs", {})
    monkeypatch.setattr(api, "Thread", partial(_thread, threads))
    try:
        yield _http_client(monkeypatch, cast(Spotify, spotify)), spotify
    finally:
        _stop(threads)


def _queue_review(spotify: FakeSpotify) -> None:
    spotify.playlists["queue"] = spotify.playlists["new"]
    filler = raw_track(
        "filler", "Filler", raw_release("filler-album", "Filler"), artist_id="other"
    )
    spotify.playlists["new"] = [filler] * 10


def _start(http: TestClient, command: str, preview: bool = False) -> str:
    response = http.post(f"/commands/{command}", params={"dry_run": preview})
    assert response.status_code == 202, response.text
    return str(response.json()["job_id"])


def _wait(http: TestClient, command: str, job: str, status: str) -> dict[str, object]:
    deadline = monotonic() + 3
    while monotonic() < deadline:
        response = http.get(f"/commands/{command}-jobs/{job}")
        assert response.status_code == 200
        value = cast(dict[str, object], response.json())
        if value["status"] == status and (status == "waiting" or value["completed_at"]):
            return value
        assert value["status"] == status or value["status"] not in {
            "failed",
            "paused",
            "cancelled",
            "completed",
        }, value
        sleep(0.01)
    raise AssertionError(f"{command} did not reach {status}")


def _choose(http: TestClient, command: str, job: str, choice: str) -> None:
    response = http.post(
        f"/commands/{command}-jobs/{job}/choice", json={"choice": choice}
    )
    assert response.status_code == 200, response.text


@pytest.mark.parametrize("command", ["flush-new-kids", "flush-queue-2"])
@pytest.mark.parametrize("preview", [False, True])
def test_http_choices_reach_real_planning_and_effects(
    discovery_http: tuple[TestClient, FakeSpotify], command: str, preview: bool
) -> None:
    """Actual job workers preserve choice validation, results and preview mutations.

    Args:
        discovery_http: Real HTTP handlers over synthetic external services.
        command: Public discovery workflow route.
        preview: Whether remote mutations are suppressed.
    """
    http, spotify = discovery_http
    if command == "flush-queue-2":
        _queue_review(spotify)
    job = _start(http, command, preview)
    waiting = _wait(http, command, job, "waiting")
    pending = cast(dict[str, object], waiting["new_kids_pending_choice"])
    assert pending["artist"] == "Artist"
    invalid = http.post(
        f"/commands/{command}-jobs/{job}/choice", json={"choice": "missing"}
    )
    assert invalid.status_code == 400
    _choose(http, command, job, "following")
    result = _wait(http, command, job, "completed")
    assert result["advanced"] == result["processed"] == 1
    playlist = "queue" if command == "flush-queue-2" else "new"
    assert spotify.mutations == (
        [] if preview else [("add", playlist, "target"), ("remove", playlist, "source")]
    )


def test_http_restart_reuses_saved_plan_after_replacement_write(
    discovery_http: tuple[TestClient, FakeSpotify],
) -> None:
    """A failed source removal resumes without duplicate append or another choice.

    Args:
        discovery_http: Real workers sharing isolated saved state and live playlists.
    """
    http, spotify = discovery_http
    spotify.fail_playlist_delete_once = "new"
    job = _start(http, "flush-new-kids")
    _wait(http, "flush-new-kids", job, "waiting")
    _choose(http, "flush-new-kids", job, "following")
    failed = _wait(http, "flush-new-kids", job, "failed")
    assert "interrupted after playlist add" in str(failed["detail"])
    completed = _wait(
        http, "flush-new-kids", _start(http, "flush-new-kids"), "completed"
    )
    assert completed["advanced"] == 1
    assert spotify.mutations == [("add", "new", "target"), ("remove", "new", "source")]


@pytest.mark.parametrize("command", ["flush-new-kids", "flush-queue-2"])
def test_cli_choice_executes_actual_discovery_preview(
    discovery_http: tuple[TestClient, FakeSpotify], command: str
) -> None:
    """CLI prompts reach the real migrated planner, executor and summary renderer.

    Args:
        discovery_http: Scoped CLI configuration and external-service simulations.
        command: Public discovery command.
    """
    _http, spotify = discovery_http
    if command == "flush-queue-2":
        _queue_review(spotify)
    result = CliRunner().invoke(main.app, [command, "--dry-run"], input="1\n")
    assert result.exit_code == 0, result.output
    assert "Target" in result.output and "Would add" in result.output
    assert spotify.mutations == []
