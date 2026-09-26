"""Exercise real Slow Listening HTTP choices through the migrated use case."""

from collections.abc import Callable
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
from tests.interfaces.test_vertical_slices import _http_client
from tests.routines.test_slow_listening import FakeSpotify
from tests.routines.test_slow_listening import raw_release
from tests.routines.test_slow_listening import raw_track


def _spotify() -> FakeSpotify:
    spotify = FakeSpotify()
    first = raw_release("first", "First", artist_id="artist", total_tracks=1)
    second = raw_release("second", "Second", artist_id="artist", total_tracks=1)
    source = raw_track("source", "Source", first, artist_id="artist")
    target = raw_track("target", "Target", second, artist_id="artist")
    spotify.playlists["slow"] = [source]
    spotify.release_tracks = {"first": [source], "second": [target]}
    spotify.artist_releases = {"artist": [first, second]}
    return spotify


def _thread(
    threads: list[Thread],
    *,
    target: Callable[..., None],
    args: tuple[object, ...],
    name: str,
    daemon: bool,
) -> Thread:
    worker = Thread(target=target, args=args, name=name, daemon=daemon)
    threads.append(worker)
    return worker


def _stop(threads: list[Thread]) -> None:
    for job in api._blast_jobs.values():
        job.cancel_event.set()
        job.choice_event.set()
    for thread in threads:
        thread.join(timeout=3)
        assert not thread.is_alive()


@pytest.fixture
def slow_http(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, FakeSpotify]]:
    """Bind real workers to synthetic Spotify facts and isolated runtime state.

    Args:
        monkeypatch: Scoped configuration and client dependency overrides.

    Yields:
        HTTP client and mutable fake Spotify server, with worker cleanup guaranteed.
    """
    spotify = _spotify()
    threads: list[Thread] = []
    settings = Mock(return_value=SimpleNamespace(slow_listening_playlist="slow"))
    monkeypatch.setattr(api, "Settings", settings)
    monkeypatch.setattr(main, "Settings", settings)
    monkeypatch.setattr(main, "review_client", Mock(return_value=spotify))
    monkeypatch.setattr(api, "_blast_jobs", {})
    monkeypatch.setattr(api, "Thread", partial(_thread, threads))
    try:
        yield _http_client(monkeypatch, cast(Spotify, spotify)), spotify
    finally:
        _stop(threads)


def _start(http: TestClient, dry_run: bool = False) -> str:
    response = http.post("/commands/flush-slow-listening", params={"dry_run": dry_run})
    assert response.status_code == 202, response.text
    return str(response.json()["job_id"])


def _wait(http: TestClient, job_id: str, status: str) -> dict[str, object]:
    deadline = monotonic() + 3
    while monotonic() < deadline:
        response = http.get(f"/commands/flush-slow-listening-jobs/{job_id}")
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
    raise AssertionError(f"Slow Listening did not reach {status}")


def _choose(
    http: TestClient, job_id: str, choice: str, order: list[str] | None = None
) -> None:
    body: dict[str, object] = {"choice": choice}
    if order is not None:
        body["order"] = order
    response = http.post(
        f"/commands/flush-slow-listening-jobs/{job_id}/choice", json=body
    )
    assert response.status_code == 200, response.text


def _advance(http: TestClient, job_id: str) -> None:
    waiting = _wait(http, job_id, "waiting")
    pending = cast(dict[str, object], waiting["slow_listening_pending_choice"])
    assert pending["kind"] == "release_order"
    _choose(http, job_id, "order", ["first", "second"])
    waiting = _wait(http, job_id, "waiting")
    pending = cast(dict[str, object], waiting["slow_listening_pending_choice"])
    assert pending["kind"] == "track"
    assert pending["target_track"] == "Target"
    _choose(http, job_id, "advance")


@pytest.mark.parametrize("dry_run", [False, True])
def test_http_executes_tie_and_track_choices(
    slow_http: tuple[TestClient, FakeSpotify], dry_run: bool
) -> None:
    """Real HTTP choices flow through planning, effects and result translation.

    Args:
        slow_http: Real worker and simulated remote playlist.
        dry_run: Whether mutations are suppressed while retaining choice flow.
    """
    http, spotify = slow_http
    job_id = _start(http, dry_run)
    _advance(http, job_id)
    result = _wait(http, job_id, "completed")
    assert result["advanced"] == result["processed"] == 1
    results = cast(list[dict[str, object]], result["slow_listening_results"])
    assert results[0]["target_track"] == "Target"
    assert spotify.mutations == (
        [] if dry_run else [("add", "target"), ("remove", "source")]
    )


def test_http_completion_acknowledgement_runs_after_final_removal(
    slow_http: tuple[TestClient, FakeSpotify],
) -> None:
    """The UI receives completion only after the final marker has been removed.

    Args:
        slow_http: Real worker and simulated remote playlist.
    """
    http, spotify = slow_http
    first_job = _start(http)
    _advance(http, first_job)
    _wait(http, first_job, "completed")
    job_id = _start(http)
    waiting = _wait(http, job_id, "waiting")
    pending = cast(dict[str, object], waiting["slow_listening_pending_choice"])
    assert pending["kind"] == "completion"
    assert spotify.playlists["slow"] == []
    _choose(http, job_id, "continue")
    result = _wait(http, job_id, "completed")
    assert result["completed_artists"] == 1
    assert result["slow_listening_pending_choice"] is None


def test_http_restart_uses_saved_plan_after_accepted_append(
    slow_http: tuple[TestClient, FakeSpotify],
) -> None:
    """A resumed job finishes the saved transition without another prompt or append.

    Args:
        slow_http: Real worker and simulated remote playlist.
    """
    http, spotify = slow_http
    spotify.fail_next_delete = True
    failed_job = _start(http)
    _advance(http, failed_job)
    failed = _wait(http, failed_job, "failed")
    assert "interrupted after add" in str(failed["detail"])
    resumed_job = _start(http)
    result = _wait(http, resumed_job, "completed")
    assert result["advanced"] == 1
    assert spotify.mutations == [("add", "target"), ("remove", "source")]


def test_cli_executes_real_tie_and_track_choices(
    slow_http: tuple[TestClient, FakeSpotify],
) -> None:
    """The existing CLI prompts reach the complete application workflow.

    Args:
        slow_http: Scoped CLI settings and synthetic Spotify client.
    """
    _http, spotify = slow_http
    result = CliRunner().invoke(
        main.app, ["flush-slow-listening", "--dry-run"], input="1,2\na\n"
    )
    assert result.exit_code == 0, result.output
    assert "Target" in result.stdout
    assert "Would add" in result.stdout
    assert spotify.mutations == []
