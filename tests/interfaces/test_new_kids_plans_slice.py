"""Real web transfers and subsequent saved-plan progression over isolated state."""

from collections.abc import Iterator
from copy import deepcopy
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


def _existing(spotify: NewKidsPlanSpotify, alias: bool = False) -> None:
    marker = deepcopy(spotify.release_tracks["b" * 22][1])
    if alias:
        marker.update(id="legacy-marker", uri="spotify:track:legacy-marker")
    spotify.playlists["new"] = [marker]
    spotify.playlists["queue"] = []


def _migrate(
    http: TestClient,
    job: str,
    pending: dict[str, object],
    resolved: str | None = None,
    confirmed: bool = False,
) -> int:
    return http.post(
        f"/commands/flush-new-kids-jobs/{job}/choice",
        json={
            "choice": "plan_select",
            "release_ids": [key * 22 for key in "abcd"],
            "request_id": pending["request_id"],
            "current_release_id": resolved,
            "confirm_current": confirmed,
        },
    ).status_code


@pytest.mark.parametrize("preview", [False, True])
def test_existing_artist_migration_resumes_at_current_playlist_track(
    plan_http: tuple[TestClient, NewKidsPlanSpotify], preview: bool
) -> None:
    """The current second album counts, and its last track advances to album three.

    Args:
        plan_http: Actual jobs and shared namespace.
        preview: Whether saved progress and playlist effects are suppressed.
    """
    http, spotify = plan_http
    _existing(spotify)
    access = new_kids._state_access(new_kids.DEFAULT_STATE_PATH, None)
    before = access.load()
    job = _start(http, preview=preview)
    pending = _pending(http, job)
    assert pending["migration"] is True
    assert pending["current_release_id"] == "b" * 22
    assert pending["selected_release_ids"] == ["b" * 22]
    assert _migrate(http, job, pending) == 200
    result = _wait(http, job, "completed")
    rows = cast(list[dict[str, object]], result["new_kids_results"])
    assert rows[0]["source_track"] == "Second studio · track 2"
    assert (
        rows[0]["target_release"] == "Third studio" and rows[0]["release_number"] == 3
    )
    state = access.load()
    if preview:
        assert state == before and spotify.mutations == []
        return
    assert spotify.playlists["new"][0]["id"] == "c" * 20 + "00"
    backup = cast(dict[str, object], state["release_plan_migration_backup"])
    assert backup["namespace"] == before
    _wait(http, _start(http), "completed")
    assert spotify.playlists["new"][0]["id"] == "c" * 20 + "01"


def test_migration_cannot_omit_current_album_and_skip_does_not_fall_back(
    plan_http: tuple[TestClient, NewKidsPlanSpotify],
) -> None:
    """An unaccepted migration cannot trigger old scrobble-driven progression.

    Args:
        plan_http: Actual locked submissions and worker.
    """
    http, spotify = plan_http
    _existing(spotify)
    job = _start(http)
    pending = _pending(http, job)
    assert _choose(http, job, pending, [key * 22 for key in "acde"]) == 400
    response = http.post(
        f"/commands/flush-new-kids-jobs/{job}/choice",
        json={"choice": "__skip__", "request_id": pending["request_id"]},
    )
    assert response.status_code == 200
    result = _wait(http, job, "completed")
    assert result["new_kids_results"] == [] and spotify.mutations == []


@pytest.mark.parametrize("edition_suffix", ["", " - Remastered"])
def test_migration_requires_explicit_resolution_of_title_only_marker(
    plan_http: tuple[TestClient, NewKidsPlanSpotify], edition_suffix: str
) -> None:
    """A current edition is not guessed from matching album or track titles.

    Args:
        plan_http: Actual pending editor and migration stage.
        edition_suffix: Edition qualifier normalized by the confirmed mapping.
    """
    http, spotify = plan_http
    _existing(spotify, True)
    spotify.playlists["new"][0]["name"] += edition_suffix
    job = _start(http)
    pending = _pending(http, job)
    assert pending["current_release_id"] is None
    assert _migrate(http, job, pending, "b" * 22) == 400
    assert _migrate(http, job, pending, "b" * 22, True) == 200
    _wait(http, job, "completed")
    assert spotify.playlists["new"][0]["id"] == "c" * 20 + "00"


def test_cli_migration_uses_current_album_in_explicit_order(
    plan_http: tuple[TestClient, NewKidsPlanSpotify],
) -> None:
    """The terminal migration accepts a reordered plan without resetting the track.

    Args:
        plan_http: Actual command dependencies and isolated namespace.
    """
    _http, spotify = plan_http
    _existing(spotify)
    result = CliRunner().invoke(
        main.app, ["flush-new-kids", "--dry-run"], input="2,5,6,3\nyes\n"
    )
    assert result.exit_code == 0, result.output
    assert "Current album" in result.output and "Would migrate" in result.output
    assert spotify.mutations == []


@pytest.mark.parametrize("composer", [False, True])
def test_migration_advances_within_album_and_retains_logical_route(
    plan_http: tuple[TestClient, NewKidsPlanSpotify], composer: bool
) -> None:
    """Migration starts at the live track and acknowledges its route once.

    Args:
        plan_http: Actual job execution and durable namespace.
        composer: Whether a performer marker belongs to a logical composer.
    """
    http, spotify = plan_http
    _existing(spotify)
    spotify.playlists["new"] = [deepcopy(spotify.release_tracks["b" * 22][0])]
    access = new_kids._state_access(new_kids.DEFAULT_STATE_PATH, None)
    state = access.load()
    if composer:
        records = spotify.artist_releases.pop("artist")
        for record in records:
            record["artists"] = [{"id": "composer", "name": "Composer"}]
        spotify.artist_releases["composer"] = records
        state["composer_routes"] = {
            "composer": {"artist_name": "Composer", "current_track_id": "b" * 20 + "00"}
        }
        access.save(state)
    job = _start(http)
    pending = _pending(http, job)
    assert spotify.mutations == []
    assert pending["artist"] == ("Composer" if composer else "Artist")
    assert _migrate(http, job, pending) == 200
    _wait(http, job, "completed")
    assert spotify.playlists["new"][0]["id"] == "b" * 20 + "01"
    saved = access.load()
    artists = cast(dict[str, dict[str, object]], saved["artists"])
    progress = artists["composer" if composer else "artist"]
    assert "release_plan_marker" not in progress
    if composer:
        routes = cast(dict[str, dict[str, object]], saved["composer_routes"])
        assert routes["composer"]["current_track_id"] == "b" * 20 + "01"


def _dated_catalogue(spotify: NewKidsPlanSpotify) -> None:
    dates = {
        "a": "2003",
        "b": "1999",
        "c": "2001",
        "d": "2001",
        "e": "1998",
        "s": "1990",
        "l": "2005",
        "m": "Unknown",
        "q": "2010",
    }
    for record in spotify.artist_releases["artist"]:
        identity = str(record["id"])
        record["release_date"] = dates[identity[0]]


@pytest.mark.parametrize(
    "route,migration",
    [("flush-new-kids", False), ("flush-queue-2", False), ("flush-new-kids", True)],
)
def test_http_catalogue_is_chronological_but_accepted_plan_keeps_user_order(
    plan_http: tuple[TestClient, NewKidsPlanSpotify], route: str, migration: bool
) -> None:
    """Actual drafts share chronology, including optional categories and migration.

    Args:
        plan_http: Real job lifecycle and isolated synthetic services.
        route: Public command presenting the plan.
        migration: Whether the current album must be retained at its own position.
    """
    http, spotify = plan_http
    _dated_catalogue(spotify)
    if migration:
        _existing(spotify)
    job = _start(http, route)
    pending = _pending(http, job, route)
    records = cast(list[dict[str, object]], pending["releases"])
    assert [record["spotify_id"] for record in records] == [
        key * 22 for key in "sebdcalqm"
    ]
    if migration:
        assert pending["selected_release_ids"] == ["b" * 22]
    assert _choose(http, job, pending, [key * 22 for key in "abcd"], route) == 200
    _wait(http, job, "completed", route)
    expected = "c" if migration else "a"
    assert spotify.playlists["new"][0]["id"] == expected * 20 + "00"
    access = new_kids._state_access(new_kids.DEFAULT_STATE_PATH, None)
    artists = cast(dict[str, dict[str, object]], access.load()["artists"])
    plan = cast(dict[str, object], artists["artist"]["release_plan"])
    pinned = cast(list[dict[str, object]], plan["releases"])
    assert [record["spotify_id"] for record in pinned] == [key * 22 for key in "abcd"]


def test_cli_displays_chronology_and_accepts_a_different_listening_order(
    plan_http: tuple[TestClient, NewKidsPlanSpotify],
) -> None:
    """Displayed numeric choices follow chronology, rather than popularity tiers.

    Args:
        plan_http: Actual CLI resources with a synthetic discography.
    """
    _http, spotify = plan_http
    _dated_catalogue(spotify)
    result = CliRunner().invoke(
        main.app, ["flush-new-kids", "--dry-run"], input="5,2,4,3\nyes\n"
    )
    assert result.exit_code == 0, result.output
    titles = ("An EP", "Second studio", "Fourth studio", "Third studio", "First studio")
    positions = [result.output.index(title) for title in titles]
    assert positions == sorted(positions) and spotify.mutations == []
