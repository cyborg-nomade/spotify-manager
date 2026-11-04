"""Exercise real Slow Listening HTTP choices through the migrated use case."""

from collections.abc import Iterator
from time import monotonic
from time import sleep
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from spotify_manager import api
from spotify_manager import main
from spotify_manager.application.ports.spotify_client import SpotifyClient as Spotify
from spotify_manager.interfaces.http import jobs as http_jobs
from spotify_manager.interfaces.http.models.slow_listening import (
    SlowListeningPendingChoice,
)
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


def _stop() -> None:
    for job in api._blast_jobs.values():
        job.cancel_event.set()
        job.choice_event.set()


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
    settings = Mock(return_value=SimpleNamespace(slow_listening_playlist="slow"))
    monkeypatch.setattr(http_jobs, "Settings", settings)
    monkeypatch.setattr(main, "Settings", settings)
    monkeypatch.setattr(main, "_native_review_client", AsyncMock(return_value=spotify))
    monkeypatch.setattr(http_jobs, "_blast_jobs", {})
    with _http_client(monkeypatch, cast(Spotify, spotify)) as http:
        try:
            yield (http, spotify)
        finally:
            _stop()


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
    assert pending["kind"] == "release"
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


def _album_catalog(spotify: FakeSpotify) -> None:
    releases = []
    for index, name in enumerate(("First", "Second", "Third", "Fourth")):
        identity = name.lower()
        release = raw_release(
            identity, name, artist_id="artist", release_date=f"{2020 + index}-01-01"
        )
        tracks = []
        for position in range(1, 3):
            track_id = (
                "source" if index == 0 and position == 1 else f"{identity}-{position}"
            )
            tracks.append(
                raw_track(
                    track_id,
                    track_id,
                    release,
                    artist_id="artist",
                    track_number=position,
                )
            )
        spotify.release_tracks[identity] = tracks[:1] if index == 0 else tracks
        if index == 0:
            spotify.playlists["slow"] = [tracks[0]]
        releases.append(release)
    spotify.artist_releases["artist"] = releases


def _pending(http: TestClient, job_id: str) -> SlowListeningPendingChoice:
    return SlowListeningPendingChoice.model_validate(
        _wait(http, job_id, "waiting")["slow_listening_pending_choice"]
    )


def _submit(http: TestClient, job_id: str, choice: str) -> SlowListeningPendingChoice:
    pending = _pending(http, job_id)
    response = http.post(
        f"/commands/flush-slow-listening-jobs/{job_id}/choice",
        json={"choice": choice, "request_id": pending.request_id},
    )
    assert response.status_code == 200, response.text
    return pending


@pytest.mark.parametrize("preview", [False, True])
def test_http_skips_whole_albums_then_accepts_one_marker(
    slow_http: tuple[TestClient, FakeSpotify], preview: bool
) -> None:
    """Run real routes, state checkpoints and native-shaped catalog observations.

    Args:
        slow_http: Actual application with isolated effects.
        preview: Keep Spotify unchanged while producing the accepted plan.
    """
    http, spotify = slow_http
    _album_catalog(spotify)
    job = _start(http, preview)
    first = _submit(http, job, "skip_album")
    assert first.kind == "release" and first.target_release == "Second"
    assert first.releases[0].spotify_id == "second"
    assert _submit(http, job, "skip_album").target_release == "Third"
    assert _submit(http, job, "advance").target_release == "Fourth"
    result = _wait(http, job, "completed")
    outcomes = result["slow_listening_results"]
    assert outcomes[0]["skipped_albums"] == ["Second", "Third"]
    assert outcomes[0]["skipped_candidates"] == []
    assert spotify.mutations == (
        [] if preview else [("add", "fourth-1"), ("remove", "source")]
    )


@pytest.mark.parametrize("stop", ["pause", "cancel"])
def test_http_restart_retains_skipped_albums_after_pause_or_cancellation(
    slow_http: tuple[TestClient, FakeSpotify], stop: str
) -> None:
    """A new job resumes the durable decision without replaying the declined album.

    Args:
        slow_http: Actual application with detached durable state.
        stop: Pause through a choice or cancel at the next prompt.
    """
    http, spotify = slow_http
    _album_catalog(spotify)
    job = _start(http)
    _submit(http, job, "skip_album")
    assert _pending(http, job).target_release == "Third"
    if stop == "pause":
        _submit(http, job, "quit")
    else:
        assert (
            http.post(f"/commands/flush-slow-listening-jobs/{job}/cancel").status_code
            == 200
        )
    _wait(http, job, "paused" if stop == "pause" else "cancelled")
    assert spotify.mutations == []
    resumed = _start(http)
    assert _submit(http, resumed, "advance").target_release == "Third"
    result = _wait(http, resumed, "completed")
    assert result["slow_listening_results"][0]["skipped_albums"] == ["Second"]
    assert spotify.album_track_calls.count("second") == 1


def test_http_album_skip_rejects_stale_tokens_and_preserves_reload_identity(
    slow_http: tuple[TestClient, FakeSpotify],
) -> None:
    """A repeated old button cannot skip the following album accidentally.

    Args:
        slow_http: Actual reconnectable jobs and submission handler.
    """
    http, spotify = slow_http
    _album_catalog(spotify)
    job = _start(http, True)
    old = _submit(http, job, "skip_album")
    current = _pending(http, job)
    assert current.request_id != old.request_id
    active = http.get("/commands/flush-slow-listening-jobs").json()[0]
    assert active["slow_listening_pending_choice"]["request_id"] == current.request_id
    path = f"/commands/flush-slow-listening-jobs/{job}/choice"
    assert (
        http.post(
            path, json={"choice": "skip_album", "request_id": old.request_id}
        ).status_code
        == 409
    )
    assert _pending(http, job) == current
    _submit(http, job, "advance")
    assert _wait(http, job, "completed")["advanced"] == 1
    assert spotify.mutations == []


def test_http_does_not_offer_or_accept_album_skip_inside_the_current_album(
    slow_http: tuple[TestClient, FakeSpotify],
) -> None:
    """The new action is limited to proposed releases beyond the current edition.

    Args:
        slow_http: Actual planning and choice validation.
    """
    http, spotify = slow_http
    _album_catalog(spotify)
    current = spotify.playlists["slow"][0]
    release = cast(dict[str, object], current["album"])
    spotify.release_tracks["first"].append(
        raw_track("within", "Within", release, artist_id="artist", track_number=2)
    )
    job = _start(http, True)
    pending = _pending(http, job)
    assert pending.kind == "track" and pending.target_track == "Within"
    response = http.post(
        f"/commands/flush-slow-listening-jobs/{job}/choice",
        json={"choice": "skip_album", "request_id": pending.request_id},
    )
    assert response.status_code == 400
    _submit(http, job, "advance")
    assert _wait(http, job, "completed")["advanced"] == 1


def test_cli_skips_albums_pauses_and_resumes_through_real_application(
    slow_http: tuple[TestClient, FakeSpotify],
) -> None:
    """CLI uses the same durable album decisions as web runs.

    Args:
        slow_http: Scoped CLI settings and synthetic Spotify client.
    """
    _http, spotify = slow_http
    _album_catalog(spotify)
    first = CliRunner().invoke(main.app, ["flush-slow-listening"], input="r\nq\n")
    assert first.exit_code == 0, first.output
    assert "skip album (r)" in first.output and "paused" in first.output
    assert spotify.mutations == []
    resumed = CliRunner().invoke(main.app, ["flush-slow-listening"], input="a\n")
    assert resumed.exit_code == 0, resumed.output
    assert "Third" in resumed.output and "Skipped albums: Second" in resumed.output
    assert spotify.mutations == [("add", "third-1"), ("remove", "source")]


def test_http_preview_pause_does_not_claim_durable_progress_was_saved(
    slow_http: tuple[TestClient, FakeSpotify],
) -> None:
    """Keep preview pause messaging consistent with suppressed checkpoints.

    Args:
        slow_http: Actual preview execution with isolated state and effects.
    """
    http, spotify = slow_http
    _album_catalog(spotify)
    job = _start(http, True)
    _submit(http, job, "skip_album")
    _submit(http, job, "quit")
    result = _wait(http, job, "paused")
    assert "preview decisions were not saved" in result["detail"]
    again = _start(http, True)
    assert _submit(http, again, "advance").target_release == "Second"
    _wait(http, again, "completed")
    assert spotify.mutations == []
