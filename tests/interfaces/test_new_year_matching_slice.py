"""Real annual HTTP/CLI paths with observed catalog data and isolated effects."""

import json
from collections.abc import Iterator
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from spotify_manager import main
from spotify_manager.application.ports.spotify_client import SpotifyClient
from spotify_manager.bootstrap import clients
from spotify_manager.interfaces.http import jobs
from spotify_manager.routines import scrobble_history
from tests.interfaces.test_discovery_slice import _wait
from tests.interfaces.test_slow_listening_slice import _stop
from tests.interfaces.test_vertical_slices import _http_client
from tests.support.annual_matching import BLAST
from tests.support.annual_matching import MEMORY
from tests.support.annual_matching import PALACE
from tests.support.annual_matching import QUEUE
from tests.support.annual_matching import AnnualMatchingHistory
from tests.support.annual_matching import AnnualMatchingSpotify
from tests.support.runtime_resources import provided_lastfm


def annual_settings() -> SimpleNamespace:
    """Supply only synthetic destinations and the isolated history account.

    Returns:
        Complete annual settings consumed by the real workflow.
    """
    return SimpleNamespace(
        blast_from_the_past_playlist=BLAST,
        palace_of_memory_playlist=PALACE,
        discography_memory_lane_playlist=MEMORY,
        the_queue_3_playlist=QUEUE,
        lastfm_api_key="test-key",
        lastfm_username="review",
    )


@pytest.fixture
def annual_http(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, AnnualMatchingSpotify]]:
    """Bind real annual jobs to scripted external services without replacing stages.

    Args:
        monkeypatch: Scoped settings and external-client substitutions.

    Yields:
        Real HTTP client and recorded synthetic Spotify effects.
    """
    spotify = AnnualMatchingSpotify()
    scrobble_history.DEFAULT_SCROBBLES_PATH.write_text(
        json.dumps({"username": "review", "scrobbles": []})
    )
    monkeypatch.setattr(jobs, "Settings", annual_settings)
    monkeypatch.setattr(main, "Settings", annual_settings)
    monkeypatch.setattr(main, "_native_client", AsyncMock(return_value=spotify))
    monkeypatch.setattr(
        clients, "LastFmClient", Mock(return_value=AnnualMatchingHistory())
    )
    monkeypatch.setattr(clients, "AsyncLastFmClient", provided_lastfm)
    monkeypatch.setattr(jobs, "_blast_jobs", {})
    with _http_client(monkeypatch, cast(SpotifyClient, spotify)) as http:
        try:
            yield http, spotify
        finally:
            _stop()


def _start(http: TestClient, preview: bool = True) -> str:
    response = http.post(
        "/commands/new-year", params={"year": 2025, "dry_run": preview}
    )
    assert response.status_code == 202, response.text
    return str(response.json()["job_id"])


def _choose(http: TestClient, job: str, identity: str) -> dict[str, object]:
    result = _wait(http, "new-year", job, "waiting")
    pending = cast(dict[str, object], result["track_match_pending_choice"])
    response = http.post(
        f"/commands/new-year-jobs/{job}/match",
        json={"request_id": pending["request_id"], "choice": identity},
    )
    assert response.status_code == 200, response.text
    return pending


@pytest.mark.parametrize("preview", [False, True])
def test_actual_annual_workers_select_observed_track_and_album(
    annual_http: tuple[TestClient, AnnualMatchingSpotify], preview: bool
) -> None:
    """Resolve the reported track and an album without replacing application stages.

    Args:
        annual_http: Actual routes, workers and isolated external resources.
        preview: Suppress all playlist writes while retaining the complete plan.
    """
    http, spotify = annual_http
    job = _start(http, preview)
    tracks = _choose(http, job, "3EYoNZwkuyJN7JTqt2djEM")
    assert tracks["kind"] == "track"
    waiting = _wait(http, "new-year", job, "waiting")
    albums = waiting["track_match_pending_choice"]
    assert albums["kind"] == "album"
    identity = albums["albums"][0]["spotify_id"]
    _choose(http, job, identity)
    result = _wait(http, "new-year", job, "completed")
    plan = result["new_year_result"]["plan"]
    assert plan["tracks"][0]["uri"] == "spotify:track:3EYoNZwkuyJN7JTqt2djEM"
    assert plan["albums"][0]["uri"] == "spotify:track:first"
    assert bool(spotify.writes) is not preview
    assert result["track_match_pending_choice"] is None


def test_actual_annual_drops_remain_visible_and_do_not_abort_preview(
    annual_http: tuple[TestClient, AnnualMatchingSpotify],
) -> None:
    """Reject track, album and artist markers while completing a write-free preview.

    Args:
        annual_http: Actual annual application with isolated external observations.
    """
    http, spotify = annual_http
    job = _start(http)
    for _index in range(3):
        _choose(http, job, "")
    result = _wait(http, "new-year", job, "completed")
    plan = result["new_year_result"]["plan"]
    assert all(
        plan[kind][0]["dropped"] is True for kind in ("tracks", "albums", "artists")
    )
    assert all("uri" not in plan[kind][0] for kind in ("tracks", "albums", "artists"))
    assert spotify.writes == []


def test_actual_annual_wait_reconnect_rejects_stale_requests_and_cancels(
    annual_http: tuple[TestClient, AnnualMatchingSpotify],
) -> None:
    """Preserve the pending request on reload and reject invalid or late decisions.

    Args:
        annual_http: Actual annual routes with isolated external services.
    """
    http, spotify = annual_http
    job = _start(http)
    result = _wait(http, "new-year", job, "waiting")
    pending = result["track_match_pending_choice"]
    assert (
        http.get("/commands/new-year-jobs").json()[0]["track_match_pending_choice"]
        == pending
    )
    path = f"/commands/new-year-jobs/{job}"
    assert (
        http.post(
            path + "/match", json={"request_id": "stale", "choice": ""}
        ).status_code
        == 409
    )
    assert (
        http.post(
            path + "/match",
            json={"request_id": pending["request_id"], "choice": "unoffered"},
        ).status_code
        == 400
    )
    assert http.post(path + "/cancel").status_code == 200
    result = _wait(http, "new-year", job, "cancelled")
    assert result["track_match_pending_choice"] is None
    assert spotify.writes == []


@pytest.mark.parametrize("answers", ["1\n1\n", "n\nn\nn\n"])
def test_actual_annual_cli_can_select_or_drop_in_dry_run(
    annual_http: tuple[TestClient, AnnualMatchingSpotify], answers: str
) -> None:
    """Use the same explicit track and album decisions through the real CLI.

    Args:
        annual_http: Scoped CLI settings, history and Spotify simulation.
        answers: Accepted candidate numbers or explicit no-match responses.
    """
    _http, spotify = annual_http
    result = CliRunner().invoke(
        main.app, ["new-year", "--year", "2025", "--dry-run"], input=answers
    )
    assert result.exit_code == 0, result.output
    assert "Choose a Spotify match" in result.output
    assert "Choose a Spotify album" in result.output
    assert "Dry run:" in result.output
    assert spotify.writes == []


def test_something_old_cli_can_reject_every_ranked_title(
    annual_http: tuple[TestClient, AnnualMatchingSpotify],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Complete real Last.fm selection with an explicit no-match summary.

    Args:
        annual_http: Shared isolated Spotify and Last.fm client factories.
        monkeypatch: Additional command configuration and client boundary.
    """
    _http, spotify = annual_http
    settings = annual_settings()
    settings.something_old_new_playlist = "x" * 22
    monkeypatch.setattr(main, "Settings", Mock(return_value=settings))
    monkeypatch.setattr(main, "_native_review_client", AsyncMock(return_value=spotify))
    rows = []
    for index in range(50):
        rows.append(
            {
                "artist": "Chevelle",
                "track": "In Debt to Earth",
                "album": "Vena Sera",
                "date": 1748779200000 + index * 1000,
            }
        )
    scrobble_history.DEFAULT_SCROBBLES_PATH.write_text(
        json.dumps({"username": "review", "scrobbles": rows})
    )
    result = CliRunner().invoke(
        main.app, ["something-old", "--dry-run"], input="1\nn\n"
    )
    assert result.exit_code == 0, result.output
    assert "Choose a Spotify match" in result.output
    assert "No Last.fm tracks were matched; Spotify was unchanged." in result.output
    assert spotify.writes == []
