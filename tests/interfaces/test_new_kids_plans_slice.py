"""Real web transfers and subsequent saved-plan progression over isolated state."""

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

from spotify_manager import main
from spotify_manager.application.ports.spotify_client import SpotifyClient
from spotify_manager.interfaces.cli.features import discovery as cli
from spotify_manager.interfaces.http import jobs
from spotify_manager.interfaces.http.workers import new_kids as worker
from spotify_manager.routines import new_kids
from tests.interfaces.test_slow_listening_slice import _stop
from tests.interfaces.test_vertical_slices import _http_client
from tests.support.new_kids_plan_spotify import EmptyPlanHistory
from tests.support.new_kids_plan_spotify import NewKidsPlanSpotify


@pytest.fixture
def plan_http(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, NewKidsPlanSpotify]]:
    """Bind actual jobs to synthetic external services and isolated durable state.

    Args:
        monkeypatch: Scoped external dependency replacements.

    Yields:
        Actual HTTP application and mutable simulated Spotify.
    """
    spotify = NewKidsPlanSpotify()
    new_kids.DEFAULT_SCROBBLES_PATH.write_text(
        '{"user":"listener","scrobbles":[{"artist":"Past Artist",'
        '"track":"Past Track","album":"Past Album","date":1700000000000}]}'
    )
    settings = Mock(
        return_value=SimpleNamespace(
            new_kids_on_the_block_playlist="new",
            the_queue_2_playlist="queue",
            great_discoveries_2026_playlist="great",
            unlucky_ones_playlist="unlucky",
            discography_newfoundland_playlist="newfoundland",
            lastfm_api_key="test-key",
            lastfm_username="listener",
        )
    )
    monkeypatch.setattr(jobs, "Settings", settings)
    monkeypatch.setattr(main, "Settings", settings)
    monkeypatch.setattr(main, "_native_review_client", AsyncMock(return_value=spotify))
    monkeypatch.setattr(worker, "lastfm_client", Mock(return_value=EmptyPlanHistory()))
    monkeypatch.setattr(
        cli, "create_lastfm_client", Mock(return_value=EmptyPlanHistory())
    )
    monkeypatch.setattr(jobs, "_blast_jobs", {})
    with _http_client(monkeypatch, cast(SpotifyClient, spotify)) as http:
        try:
            yield http, spotify
        finally:
            _stop()


def _start(
    http: TestClient, route: str = "flush-new-kids", preview: bool = False
) -> str:
    response = http.post("/commands/" + route, params={"dry_run": preview})
    assert response.status_code == 202, response.text
    return str(response.json()["job_id"])


def _wait(
    http: TestClient, job: str, status: str, route: str = "flush-new-kids"
) -> dict[str, object]:
    deadline = monotonic() + 5
    while monotonic() < deadline:
        response = http.get(f"/commands/{route}-jobs/{job}")
        assert response.status_code == 200
        value = cast(dict[str, object], response.json())
        if value["status"] == status:
            return value
        assert value["status"] not in {"failed", "cancelled", "completed"}, value[
            "detail"
        ]
        sleep(0.01)
    raise AssertionError(f"Job did not reach {status}: {value}")


def _choose(
    http: TestClient,
    job: str,
    pending: dict[str, object],
    ids: list[str],
    route: str = "flush-new-kids",
    short: bool = False,
) -> int:
    return http.post(
        f"/commands/{route}-jobs/{job}/choice",
        json={
            "choice": "plan_select",
            "release_ids": ids,
            "confirm_short": short,
            "request_id": pending["request_id"],
        },
    ).status_code


def _pending(
    http: TestClient, job: str, route: str = "flush-new-kids"
) -> dict[str, object]:
    return cast(
        dict[str, object], _wait(http, job, "waiting", route)["new_kids_pending_choice"]
    )


@pytest.mark.parametrize("route", ["flush-new-kids", "flush-queue-2"])
@pytest.mark.parametrize("preview", [False, True])
def test_plan_transfer_uses_explicit_order_in_both_commands(
    plan_http: tuple[TestClient, NewKidsPlanSpotify], route: str, preview: bool
) -> None:
    """Prefill plans start at the first chosen album and do not auto-count Queue 2.

    Args:
        plan_http: Actual HTTP lifecycle and isolated fake services.
        route: Command that performs the initial transfer.
        preview: Whether all remote and plan writes must be suppressed.
    """
    http, spotify = plan_http
    job = _start(http, route, preview)
    pending = _pending(http, job, route)
    assert pending["kind"] == "release_plan" and pending["queue_album"] == "Queue album"
    assert len(cast(list[object], pending["releases"])) == 9
    ids = [character * 22 for character in "ecal"]
    assert _choose(http, job, pending, ids, route) == 200
    result = _wait(http, job, "completed", route)
    assert len(cast(list[object], result["new_kids_prefill"])) == 1
    assert not result["new_kids_results"] and not result["new_kids_postfill"]
    state = new_kids._state_access(new_kids.DEFAULT_STATE_PATH, None).load()
    if preview:
        assert spotify.mutations == [] and state["artists"] == {}
        return
    assert spotify.playlists["new"][0]["id"] == "e" * 20 + "00"
    artists = cast(dict[str, dict[str, object]], state["artists"])
    saved = cast(dict[str, object], artists["artist"]["release_plan"])
    releases = cast(list[dict[str, object]], saved["releases"])
    assert [item["spotify_id"] for item in releases] == ids and saved["position"] == 0


def test_short_plan_requires_confirmation_and_stale_drafts_are_rejected(
    plan_http: tuple[TestClient, NewKidsPlanSpotify],
) -> None:
    """Only a complete current draft can accept an explicitly shorter plan.

    Args:
        plan_http: Actual locked job submissions.
    """
    http, spotify = plan_http
    job = _start(http)
    pending = _pending(http, job)
    assert _choose(http, job, pending, ["a" * 22]) == 400
    stale = dict(pending, request_id="stale")
    assert _choose(http, job, stale, ["a" * 22], short=True) == 409
    assert spotify.mutations == []
    assert _choose(http, job, pending, ["a" * 22], short=True) == 200
    _wait(http, job, "completed")
    assert _choose(http, job, pending, ["b" * 22], short=True) == 409


def test_saved_order_advances_after_new_invocations_without_more_choices(
    plan_http: tuple[TestClient, NewKidsPlanSpotify],
) -> None:
    """Transfer, track advance and release boundary reload the same pinned plan.

    Args:
        plan_http: Actual jobs and shared namespace.
    """
    http, spotify = plan_http
    job = _start(http)
    pending = _pending(http, job)
    assert _choose(http, job, pending, [character * 22 for character in "dabc"]) == 200
    _wait(http, job, "completed")
    _wait(http, _start(http), "completed")
    assert spotify.playlists["new"][0]["id"] == "d" * 20 + "01"
    _wait(http, _start(http), "completed")
    assert spotify.playlists["new"][0]["id"] == "a" * 20 + "00"


def test_accepted_transfer_recovers_after_actual_worker_failure(
    plan_http: tuple[TestClient, NewKidsPlanSpotify],
) -> None:
    """A new job reloads durable intent and preserves its already-added marker.

    Args:
        plan_http: Actual jobs, shared namespace and mutable remote membership.
    """
    http, spotify = plan_http
    spotify.fail_playlist_delete_once = "queue"
    job = _start(http)
    assert (
        _choose(
            http, job, _pending(http, job), [character * 22 for character in "dabc"]
        )
        == 200
    )
    _wait(http, job, "failed")
    _wait(http, _start(http), "completed")
    assert [item["id"] for item in spotify.playlists["new"]] == ["d" * 20 + "00"]
    additions = [item for item in spotify.mutations if item[0] == "add"]
    assert additions == [("add", "new", "d" * 20 + "00")]


@pytest.mark.parametrize("input_text", ["4,1,2,3\nyes\n", "all\n9\nno\n5\nyes\n"])
def test_cli_runs_the_ordered_editor_with_real_transfer_stage(
    plan_http: tuple[TestClient, NewKidsPlanSpotify], input_text: str
) -> None:
    """Exercise ordered numbers, optional categories and explicit confirmation.

    Args:
        plan_http: Isolated clients and command settings.
        input_text: Full-order or shorter-plan terminal interaction.
    """
    _http, spotify = plan_http
    result = CliRunner().invoke(
        main.app, ["flush-new-kids", "--dry-run"], input=input_text
    )
    assert result.exit_code == 0, result.output
    assert "Confirm" in result.output and "1 Queue 2 transfers" in result.output
    assert spotify.mutations == []
