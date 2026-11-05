"""Real web and terminal cellar confirmation over isolated persistent state."""

import json
from typing import cast

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from spotify_manager import main
from spotify_manager.core.state.runtime import reset_state_service
from spotify_manager.interfaces.requests.new_wine import NewWineStorage
from tests.interfaces.test_new_wine_slice import _wait
from tests.interfaces.test_new_wine_slice import wine_http as wine_http
from tests.routines.test_new_wine import FakeSpotify
from tests.routines.test_new_wine import raw_release
from tests.routines.test_new_wine import raw_track


def _seed(spotify: FakeSpotify) -> None:
    release = raw_release(
        "cellar-album", "Cellar album", artist_id="artist", total_tracks=2
    )
    first = raw_track("first", "First", release, artist_id="artist")
    second = raw_track("second", "Second", release, artist_id="artist", track_number=2)
    spotify.playlists.update(new=[], cellar=[first, second])
    spotify.release_tracks["cellar-album"] = [first, second]
    spotify.saved_album_ids = {"saved-1", "saved-2", "saved-3"}
    albums = []
    for identifier in sorted(spotify.saved_album_ids):
        albums.append(
            {
                "artist": "Artist",
                "album": identifier,
                "uri": f"spotify:album:{identifier}",
            }
        )
    storage = NewWineStorage()
    storage.albums_path.write_text(json.dumps(albums))
    storage.liked_tracks_path.write_text("[]")


def _start(http: TestClient, preview: bool = False) -> str:
    response = http.post(
        "/commands/flush-new-wine", params={"dry_run": preview, "no_discovery": True}
    )
    assert response.status_code == 202, response.text
    return str(response.json()["job_id"])


def _change_playlist(spotify: FakeSpotify, change: str) -> None:
    if change == "remove":
        spotify.playlists["cellar"].pop(0)
        return
    if change == "metadata":
        spotify.playlists["cellar"][0]["name"] = "Edited marker"
        return
    original = spotify.playlists["cellar"][0]
    tracks = []
    for index in range(10):
        tracks.append(
            {
                **original,
                "id": f"external-{index}",
                "uri": f"spotify:track:external-{index}",
            }
        )
    spotify.playlists["new"] = tracks


def _pending(http: TestClient, job: str) -> dict[str, object]:
    result = _wait(http, job, "waiting")
    pending = cast(dict[str, object], result["pending_choice"])
    assert pending["kind"] == "cellar_transfer"
    assert pending["request_id"]
    return pending


def _choose(http: TestClient, job: str, pending: dict[str, object], choice: str) -> int:
    response = http.post(
        f"/commands/flush-new-wine-jobs/{job}/choice",
        json={"choice": choice, "request_id": pending["request_id"]},
    )
    return response.status_code


@pytest.mark.parametrize("preview", [False, True])
def test_skip_then_accept_uses_actual_cellar_effects_and_history(
    wine_http: tuple[TestClient, FakeSpotify], preview: bool
) -> None:
    """Exact proposals reach application persistence and append-before-removal.

    Args:
        wine_http: Real worker and mutable Spotify observations.
        preview: Whether live effects must be suppressed.
    """
    http, spotify = wine_http
    _seed(spotify)
    job = _start(http, preview)
    first = _pending(http, job)
    assert (first["source_track"], first["saved_albums"], first["liked_tracks"]) == (
        "First",
        3,
        None,
    )
    assert _choose(http, job, first, "skip") == 200
    second = _pending(http, job)
    assert second["source_track"] == "Second"
    assert _choose(http, job, second, "accept") == 200
    result = _wait(http, job, "completed")
    refill = cast(dict[str, object], result["new_wine_refill"])
    assert (refill["added"], refill["paused"]) == (1, False)
    assert spotify.mutations == (
        [] if preview else [("add", "new", "second"), ("remove", "cellar", "second")]
    )


def test_stale_missing_and_invalid_submissions_cannot_select_another_transfer(
    wine_http: tuple[TestClient, FakeSpotify],
) -> None:
    """Old clicks cannot accept the following candidate or another choice kind.

    Args:
        wine_http: Real reconnectable worker and isolated state.
    """
    http, spotify = wine_http
    _seed(spotify)
    job = _start(http)
    first = _pending(http, job)
    missing = http.post(
        f"/commands/flush-new-wine-jobs/{job}/choice", json={"choice": "accept"}
    )
    assert missing.status_code == 409
    assert _choose(http, job, first, "cellar-album") == 400
    assert _choose(http, job, first, "skip") == 200
    second = _pending(http, job)
    assert first["request_id"] != second["request_id"]
    assert _choose(http, job, first, "accept") == 409
    assert spotify.mutations == []
    assert _choose(http, job, second, "quit") == 200
    _wait(http, job, "paused")


def test_quit_and_new_runtime_preserve_skips_but_reoffer_unaccepted_candidate(
    wine_http: tuple[TestClient, FakeSpotify],
) -> None:
    """Shared state survives service reconstruction and does not imply acceptance.

    Args:
        wine_http: Real workers sharing isolated central state.
    """
    http, spotify = wine_http
    _seed(spotify)
    job = _start(http)
    assert _choose(http, job, _pending(http, job), "skip") == 200
    second = _pending(http, job)
    assert _choose(http, job, second, "quit") == 200
    result = _wait(http, job, "paused")
    assert cast(dict[str, object], result["new_wine_refill"])["paused"] is True
    reset_state_service()
    resumed = _start(http)
    pending = _pending(http, resumed)
    assert (
        pending["source_track"] == "Second"
        and pending["request_id"] != second["request_id"]
    )
    assert _choose(http, resumed, pending, "accept") == 200
    _wait(http, resumed, "completed")
    assert [row["id"] for row in spotify.playlists["cellar"]] == ["first"]


def test_cancel_and_overlap_keep_both_playlists_unchanged(
    wine_http: tuple[TestClient, FakeSpotify],
) -> None:
    """Waiting jobs retain their owning command and observe cancellation.

    Args:
        wine_http: Real worker with synthetic observations.
    """
    http, spotify = wine_http
    _seed(spotify)
    job = _start(http)
    pending = _pending(http, job)
    assert http.post("/commands/flush-new-wine").status_code == 409
    assert http.post(f"/commands/flush-new-wine-jobs/{job}/cancel").status_code == 200
    _wait(http, job, "cancelled")
    assert _choose(http, job, pending, "accept") == 409
    assert spotify.mutations == []


@pytest.mark.parametrize("change", ["remove", "metadata", "full"])
def test_changed_playlist_during_prompt_prevents_transfer(
    wine_http: tuple[TestClient, FakeSpotify], change: str
) -> None:
    """A vanished reviewed marker is not reintroduced to New Wine.

    Args:
        wine_http: Real worker with externally editable simulated playlists.
        change: Changed source presence, source metadata or destination capacity.
    """
    http, spotify = wine_http
    _seed(spotify)
    job = _start(http)
    pending = _pending(http, job)
    _change_playlist(spotify, change)
    assert _choose(http, job, pending, "accept") == 200
    result = _wait(http, job, "failed")
    assert "during confirmation" in str(result["detail"])
    assert spotify.mutations == []


def test_accepted_append_recovers_without_reconfirmation_or_duplicates(
    wine_http: tuple[TestClient, FakeSpotify],
) -> None:
    """An interrupted source removal resumes the accepted transfer intent.

    Args:
        wine_http: Fresh workers sharing persisted intent and remote effects.
    """
    http, spotify = wine_http
    _seed(spotify)
    spotify.playlists["cellar"].pop()
    spotify.fail_next_delete = True
    job = _start(http)
    assert _choose(http, job, _pending(http, job), "accept") == 200
    _wait(http, job, "failed")
    reset_state_service()
    _wait(http, _start(http), "completed")
    assert spotify.mutations == [("add", "new", "first"), ("remove", "cellar", "first")]


@pytest.mark.parametrize("choice,expected", [("s\na\n", "skipped"), ("q\n", "paused")])
def test_cli_no_discovery_has_explicit_transfer_controls(
    wine_http: tuple[TestClient, FakeSpotify], choice: str, expected: str
) -> None:
    """Terminal decisions execute the same application policy and preview safeguards.

    Args:
        wine_http: Scoped terminal client, configuration and storage.
        choice: Scripted skip/accept or quit interaction.
        expected: Outcome displayed by the real command.
    """
    _http, spotify = wine_http
    _seed(spotify)
    result = CliRunner().invoke(
        main.app, ["flush-new-wine", "--dry-run", "--no-discovery"], input=choice
    )
    assert result.exit_code == 0, result.output
    assert "Cellar album" in result.output and expected in result.output.lower()
    assert spotify.mutations == []
