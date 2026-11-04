"""Exercise successor review through real HTTP workers and terminal execution."""

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
from spotify_manager.interfaces.http.models.requeue import RequeuePendingChoice
from tests.interfaces.test_vertical_slices import _http_client
from tests.routines.test_requeue_for_a_dream import FakeSpotify
from tests.routines.test_requeue_for_a_dream import configured_spotify
from tests.routines.test_requeue_for_a_dream import raw_release
from tests.routines.test_requeue_for_a_dream import raw_track


PATH = "/commands/flush-requeue-for-a-dream-jobs"


def _catalog() -> FakeSpotify:
    spotify, _source, _target = configured_spotify()
    for index, name in [(3, "Third"), (4, "Fourth")]:
        release = raw_release(f"r{index}", name, release_date=f"202{index}-01-01")
        spotify.releases.append(release)
        spotify.release_tracks[f"r{index}"] = [
            raw_track(f"t{index}", f"{name} opening", release)
        ]
    return spotify


def _stop_jobs() -> None:
    for job in api._blast_jobs.values():
        job.cancel_event.set()
        job.choice_event.set()


@pytest.fixture
def requeue_http(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, FakeSpotify]]:
    """Bind actual delivery and application stages to isolated Spotify effects.

    Args:
        monkeypatch: Scoped settings and external-client overrides.

    Yields:
        Real HTTP client and mutable external observations.
    """
    spotify = _catalog()
    settings = Mock(
        return_value=SimpleNamespace(reqeueue_for_a_dream_playlist="requeue")
    )
    monkeypatch.setattr(http_jobs, "Settings", settings)
    monkeypatch.setattr(main, "Settings", settings)
    monkeypatch.setattr(main, "_native_review_client", AsyncMock(return_value=spotify))
    monkeypatch.setattr(http_jobs, "_blast_jobs", {})
    with _http_client(monkeypatch, cast(Spotify, spotify)) as http:
        try:
            yield http, spotify
        finally:
            _stop_jobs()


def _start(http: TestClient, preview: bool = False) -> str:
    response = http.post(
        "/commands/flush-requeue-for-a-dream", params={"dry_run": preview}
    )
    assert response.status_code == 202, response.text
    return str(response.json()["job_id"])


def _wait(http: TestClient, job_id: str, status: str) -> dict[str, object]:
    deadline = monotonic() + 3
    while monotonic() < deadline:
        response = http.get(f"{PATH}/{job_id}")
        assert response.status_code == 200
        result = cast(dict[str, object], response.json())
        if result["status"] == status and (
            status == "waiting" or result["completed_at"]
        ):
            return result
        assert (
            result["status"] not in {"failed", "completed", "cancelled"}
            or result["status"] == status
        ), result
        sleep(0.01)
    raise AssertionError(f"Requeue job did not reach {status}")


def _pending(http: TestClient, job_id: str) -> RequeuePendingChoice:
    value = _wait(http, job_id, "waiting")
    return RequeuePendingChoice.model_validate(value["requeue_pending_choice"])


def _choose(http: TestClient, job_id: str, choice: str) -> RequeuePendingChoice:
    pending = _pending(http, job_id)
    response = http.post(
        f"{PATH}/{job_id}/choice",
        json={"choice": choice, "request_id": pending.request_id},
    )
    assert response.status_code == 200, response.text
    return pending


@pytest.mark.parametrize("preview", [False, True])
def test_repeated_skips_accept_the_selected_successor(
    requeue_http: tuple[TestClient, FakeSpotify], preview: bool
) -> None:
    """Only the explicitly accepted successor supplies the next marker.

    Args:
        requeue_http: Real application over a simulated catalog and playlist.
        preview: Suppress remote effects and audit writes.
    """
    http, spotify = requeue_http
    job = _start(http, preview)
    assert _choose(http, job, "skip").release_name == "Second"
    assert _choose(http, job, "skip").release_name == "Third"
    assert _choose(http, job, "accept").release_name == "Fourth"
    result = _wait(http, job, "completed")
    assert result["requeue_target_release"] == "Fourth"
    assert result["requeue_target_track"] == "Fourth opening"
    assert result["requeue_pending_choice"] is None
    assert spotify.mutations == ([] if preview else [("add", "t4"), ("remove", "t1")])


@pytest.mark.parametrize("preview", [False, True])
def test_exhaustion_previews_or_applies_original_artist_completion(
    requeue_http: tuple[TestClient, FakeSpotify], preview: bool
) -> None:
    """Skipping every remaining album clearly reports completion and its effects.

    Args:
        requeue_http: Real application with three eligible successors.
        preview: Keep the source marker while previewing removal.
    """
    http, spotify = requeue_http
    job = _start(http, preview)
    for name in ("Second", "Third", "Fourth"):
        assert _choose(http, job, "skip").release_name == name
    result = _wait(http, job, "completed")
    assert result["requeue_action"] == "drop"
    assert "all remaining eligible albums were skipped" in str(result["detail"])
    assert result["playlist_length_after"] == 0
    assert spotify.mutations == ([] if preview else [("remove", "t1")])


@pytest.mark.parametrize("endpoint", ["choice", "cancel"])
def test_cancellation_clears_waiting_without_changes_and_new_job_starts_fresh(
    requeue_http: tuple[TestClient, FakeSpotify], endpoint: str
) -> None:
    """Both cancellation controls wake the waiter and abandon transient selections.

    Args:
        requeue_http: Real application with isolated playlist effects.
        endpoint: Cancel decision or owning job's cancellation endpoint.
    """
    http, spotify = requeue_http
    job = _start(http)
    _choose(http, job, "skip")
    pending = _pending(http, job)
    assert pending.release_name == "Third"
    response = http.post(
        f"{PATH}/{job}/{endpoint}",
        json={"choice": "cancel", "request_id": pending.request_id},
    )
    assert response.status_code == 200
    result = _wait(http, job, "cancelled")
    assert result["requeue_pending_choice"] is None
    assert spotify.mutations == [] and spotify.playlist[0]["id"] == "t1"
    fresh = _start(http, True)
    assert _choose(http, fresh, "cancel").release_name == "Second"
    _wait(http, fresh, "cancelled")


def test_reload_identity_stale_choices_validation_and_start_conflict(
    requeue_http: tuple[TestClient, FakeSpotify],
) -> None:
    """One rendered request is stable through polling and cannot consume its successor.

    Args:
        requeue_http: Actual HTTP job registry and worker.
    """
    http, spotify = requeue_http
    job = _start(http, True)
    pending = _pending(http, job)
    active = http.get(PATH).json()
    assert active[0]["requeue_pending_choice"] == pending.model_dump()
    assert http.post("/commands/flush-requeue-for-a-dream").status_code == 409
    assert (
        http.post(f"{PATH}/{job}/choice", json={"choice": "accept"}).status_code == 422
    )
    assert (
        http.post(
            f"{PATH}/{job}/choice",
            json={"choice": "invalid", "request_id": pending.request_id},
        ).status_code
        == 422
    )
    _choose(http, job, "skip")
    successor = _pending(http, job)
    assert successor.request_id != pending.request_id
    response = http.post(
        f"{PATH}/{job}/choice",
        json={"choice": "accept", "request_id": pending.request_id},
    )
    assert response.status_code == 409
    assert _pending(http, job) == successor and spotify.mutations == []
    _choose(http, job, "cancel")
    _wait(http, job, "cancelled")


@pytest.mark.parametrize("choice", ["accept", "skip"])
def test_changed_head_is_rejected_after_album_review(
    requeue_http: tuple[TestClient, FakeSpotify], choice: str
) -> None:
    """A concurrent head replacement prevents acceptance and exhaustion effects.

    Args:
        requeue_http: Real worker and mutable simulated Spotify.
        choice: Accept the last successor or skip it to exhaust the catalog.
    """
    http, spotify = requeue_http
    job = _start(http)
    _choose(http, job, "skip")
    _choose(http, job, "skip")
    _pending(http, job)
    spotify.playlist.insert(0, spotify.release_tracks["r3"][0])
    _choose(http, job, choice)
    result = _wait(http, job, "failed")
    assert "changed before the update" in str(result["detail"])
    assert result["requeue_pending_choice"] is None and spotify.mutations == []


@pytest.mark.parametrize("was_present", [False, True])
def test_live_duplicate_membership_is_refreshed_after_the_prompt(
    requeue_http: tuple[TestClient, FakeSpotify], was_present: bool
) -> None:
    """Concurrent tail edits cannot duplicate or lose an accepted replacement.

    Args:
        requeue_http: Real execution with fresh mutable playlist observations.
        was_present: Whether the target was initially present before review.
    """
    http, spotify = requeue_http
    target = next(
        track for track in spotify.release_tracks["r2"] if track["id"] == "t2a"
    )
    if was_present:
        spotify.playlist.append(target)
    job = _start(http)
    _pending(http, job)
    if was_present:
        spotify.playlist.remove(target)
    else:
        spotify.playlist.append(target)
    _choose(http, job, "accept")
    result = _wait(http, job, "completed")
    assert result["requeue_target_already_present"] is not was_present
    assert spotify.playlist == [target]
    assert spotify.mutations == (
        [("add", "t2a"), ("remove", "t1")] if was_present else [("remove", "t1")]
    )


@pytest.mark.parametrize("choice", ["accept", "skip"])
def test_empty_release_retains_acceptance_policy_and_can_be_skipped(
    requeue_http: tuple[TestClient, FakeSpotify], choice: str
) -> None:
    """An empty successor leaves the source or can be skipped for its successor.

    Args:
        requeue_http: Real application with an empty successor track response.
        choice: Accept the unavailable album or skip it to its successor.
    """
    http, spotify = requeue_http
    spotify.release_tracks["r2"] = []
    job = _start(http, True)
    _choose(http, job, choice)
    if choice == "skip":
        assert _choose(http, job, "accept").release_name == "Third"
    result = _wait(http, job, "completed")
    assert result["requeue_action"] == ("skip" if choice == "accept" else "advance")
    assert spotify.mutations == []


def test_cli_empty_answer_cancels_without_changes(
    requeue_http: tuple[TestClient, FakeSpotify],
) -> None:
    """The new operator prompt requires deliberate acceptance before a live effect.

    Args:
        requeue_http: Isolated terminal and external resources.
    """
    _http, spotify = requeue_http
    result = CliRunner().invoke(main.app, ["flush-requeue-for-a-dream"], input="\n")
    assert result.exit_code == 0, result.output
    assert "cancelled" in result.output and spotify.mutations == []


@pytest.mark.parametrize(
    "answers,selected", [("s\ns\na\n", "Fourth"), ("s\nc\n", None)]
)
def test_cli_uses_real_successor_review(
    requeue_http: tuple[TestClient, FakeSpotify], answers: str, selected: str | None
) -> None:
    """Real terminal input selects an album or abandons the plan without effects.

    Args:
        requeue_http: Isolated shared external resources.
        answers: Explicit Rich prompt input.
        selected: Expected accepted album, or cancellation.
    """
    _http, spotify = requeue_http
    result = CliRunner().invoke(
        main.app, ["flush-requeue-for-a-dream", "--dry-run"], input=answers
    )
    assert result.exit_code == 0, result.output
    assert "Accept album (a) / skip album (s) / cancel (c)" in result.output
    assert "Third" in result.output and spotify.mutations == []
    assert (selected or "cancelled") in result.output
