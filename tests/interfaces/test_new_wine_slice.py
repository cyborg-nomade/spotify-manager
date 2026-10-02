"""Real New Wine CLI and HTTP choices through migrated application workflows."""

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
from tests.interfaces.test_slow_listening_slice import _stop
from tests.interfaces.test_slow_listening_slice import _thread
from tests.interfaces.test_vertical_slices import _http_client
from tests.routines.test_new_wine import FakeSpotify
from tests.routines.test_new_wine import raw_release
from tests.routines.test_new_wine import raw_track


def _spotify() -> FakeSpotify:
    spotify = FakeSpotify()
    single = raw_release(
        "single", "Single", artist_id="artist", album_type="single", total_tracks=1
    )
    album = raw_release("album", "Album", artist_id="artist", total_tracks=2)
    source = raw_track("source", "Source", single, artist_id="artist")
    target = raw_track("target", "Target", album, artist_id="artist")
    next_track = raw_track("next", "Next", album, artist_id="artist", track_number=2)
    spotify.playlists.update(new=[source], cellar=[])
    spotify.release_tracks = {"single": [source], "album": [target, next_track]}
    spotify.artist_releases = {"artist": [album]}
    return spotify


@pytest.fixture
def wine_http(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, FakeSpotify]]:
    """Bind actual workers to synthetic Spotify and isolated durable state.

    Args:
        monkeypatch: Scoped settings and dependency overrides.

    Yields:
        HTTP client and simulated Spotify, with worker cleanup guaranteed.
    """
    spotify = _spotify()
    threads: list[Thread] = []
    settings = Mock(
        return_value=SimpleNamespace(
            new_wine_from_old_bottles_playlist="new",
            sauvignon_terre_neuve_playlist="sauv",
            wine_cellar_playlist="cellar",
        )
    )
    monkeypatch.setattr(api, "Settings", settings)
    monkeypatch.setattr(main, "Settings", settings)
    monkeypatch.setattr(main, "review_client", Mock(return_value=spotify))
    monkeypatch.setattr(api, "_blast_jobs", {})
    monkeypatch.setattr(api, "Thread", partial(_thread, threads))
    try:
        yield _http_client(monkeypatch, cast(Spotify, spotify)), spotify
    finally:
        _stop(threads)


def _start(http: TestClient, *, preview: bool = False, endpoints: bool = False) -> str:
    response = http.post(
        "/commands/flush-new-wine",
        params={"dry_run": preview, "choose_album_endpoints": endpoints},
    )
    assert response.status_code == 202, response.text
    return str(response.json()["job_id"])


def _wait(http: TestClient, job_id: str, status: str) -> dict[str, object]:
    deadline = monotonic() + 3
    while monotonic() < deadline:
        response = http.get(f"/commands/flush-new-wine-jobs/{job_id}")
        assert response.status_code == 200
        value = cast(dict[str, object], response.json())
        if value["status"] == status and (status == "waiting" or value["completed_at"]):
            return value
        assert value["status"] == status or value["status"] not in {
            "failed",
            "cancelled",
            "completed",
        }, value
        sleep(0.01)
    raise AssertionError(f"New Wine did not reach {status}")


def _choose(http: TestClient, job_id: str, choice: str) -> None:
    response = http.post(
        f"/commands/flush-new-wine-jobs/{job_id}/choice", json={"choice": choice}
    )
    assert response.status_code == 200, response.text


@pytest.mark.parametrize("preview", [False, True])
def test_http_release_choice_reaches_real_planner_and_effects(
    wine_http: tuple[TestClient, FakeSpotify], preview: bool
) -> None:
    """UI selections reach real planning and retain preview behavior.

    Args:
        wine_http: Real worker over synthetic observations.
        preview: Whether remote effects must be suppressed.
    """
    http, spotify = wine_http
    job = _start(http, preview=preview)
    waiting = _wait(http, job, "waiting")
    pending = cast(dict[str, object], waiting["pending_choice"])
    assert pending["source_track"] == "Source"
    invalid = http.post(
        f"/commands/flush-new-wine-jobs/{job}/choice", json={"choice": "missing"}
    )
    assert invalid.status_code == 400
    _choose(http, job, "album")
    result = _wait(http, job, "completed")
    assert result["advanced"] == result["processed"] == 1
    assert spotify.mutations == (
        [] if preview else [("add", "new", "target"), ("remove", "new", "source")]
    )


def test_http_restart_consumes_saved_plan_without_reprompting(
    wine_http: tuple[TestClient, FakeSpotify],
) -> None:
    """Accepted replacement survives a failed source removal without duplication.

    Args:
        wine_http: Real workers sharing isolated namespace and mutable playlists.
    """
    http, spotify = wine_http
    spotify.fail_next_delete = True
    failed_job = _start(http)
    _wait(http, failed_job, "waiting")
    _choose(http, failed_job, "album")
    failed = _wait(http, failed_job, "failed")
    assert "interrupted after add" in str(failed["detail"])
    result = _wait(http, _start(http), "completed")
    assert result["advanced"] == 1
    assert spotify.mutations == [("add", "new", "target"), ("remove", "new", "source")]


def test_http_endpoint_choice_routes_completed_canonical_album(
    wine_http: tuple[TestClient, FakeSpotify],
) -> None:
    """Cutoff selections travel through the HTTP prompt and exact album plan.

    Args:
        wine_http: Real worker over a two-track album.
    """
    http, spotify = wine_http
    spotify.playlists["new"] = [spotify.release_tracks["album"][0]]
    job = _start(http, endpoints=True)
    waiting = _wait(http, job, "waiting")
    pending = cast(dict[str, object], waiting["pending_choice"])
    assert pending["kind"] == "album_endpoint"
    _choose(http, job, "cutoff")
    result = _wait(http, job, "completed")
    assert result["sent_to_sauvignon"] == 1
    assert spotify.mutations == [("add", "sauv", "target"), ("remove", "new", "target")]


def test_cli_release_prompt_executes_real_preview(
    wine_http: tuple[TestClient, FakeSpotify],
) -> None:
    """The actual CLI selection callback reaches the migrated use case.

    Args:
        wine_http: Scoped CLI settings and Spotify dependency.
    """
    _http, spotify = wine_http
    result = CliRunner().invoke(main.app, ["flush-new-wine", "--dry-run"], input="1\n")
    assert result.exit_code == 0, result.output
    assert "Target" in result.output and "Would add" in result.output
    assert spotify.mutations == []
