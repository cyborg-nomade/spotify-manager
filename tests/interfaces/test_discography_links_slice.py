"""Actual web/CLI addition, selection, confirmation and mutation paths."""

import json
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
from spotify_manager.interfaces.http import jobs
from spotify_manager.interfaces.http.models.discography import DiscographyChoiceRequest
from spotify_manager.routines import discography
from tests.interfaces.test_slow_listening_slice import _stop
from tests.interfaces.test_vertical_slices import _http_client
from tests.support.discography_link_spotify import FIRST_LINK
from tests.support.discography_link_spotify import MISSING_LINK
from tests.support.discography_link_spotify import SECOND_LINK
from tests.support.discography_link_spotify import DiscographyLinkSpotify


@pytest.fixture
def discography_http(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, DiscographyLinkSpotify]]:
    """Bind real routes and workers to isolated data and synthetic Spotify.

    Args:
        monkeypatch: Scoped settings and native-client overrides.

    Yields:
        Actual HTTP application and mutable external observations.
    """
    spotify = DiscographyLinkSpotify()
    priority = discography._state_access(discography.DEFAULT_STATE_PATH, None)
    state = priority.load()
    state["next_queue"] = "newfoundland"
    priority.save(state)
    settings = Mock(
        return_value=SimpleNamespace(
            discography_newfoundland_playlist="newfoundland",
            discography_memory_lane_playlist="memory",
            discography_requeue_playlist="requeue",
            the_queue_3_playlist="queue3",
        )
    )
    monkeypatch.setattr(jobs, "Settings", settings)
    monkeypatch.setattr(main, "Settings", settings)
    monkeypatch.setattr(main, "_native_review_client", AsyncMock(return_value=spotify))
    monkeypatch.setattr(jobs, "_blast_jobs", {})
    with _http_client(monkeypatch, cast(SpotifyClient, spotify)) as http:
        try:
            yield http, spotify
        finally:
            _stop()


def _start(http: TestClient, preview: bool = True) -> str:
    response = http.post("/commands/plan-discographies", params={"dry_run": preview})
    assert response.status_code == 202, response.text
    return str(response.json()["job_id"])


def _wait(http: TestClient, job: str, status: str = "waiting") -> dict[str, object]:
    deadline = monotonic() + 5
    while monotonic() < deadline:
        response = http.get(f"/commands/plan-discographies-jobs/{job}")
        assert response.status_code == 200
        result = cast(dict[str, object], response.json())
        if result["status"] == status and (
            status == "waiting" or result["completed_at"]
        ):
            return result
        assert result["status"] == status or result["status"] not in {
            "failed",
            "cancelled",
            "completed",
        }, result
        sleep(0.01)
    raise AssertionError(f"Discographies did not reach {status}")


def _pending(http: TestClient, job: str) -> dict[str, object]:
    return cast(dict[str, object], _wait(http, job)["discography_pending_choice"])


def _submit(
    http: TestClient,
    job: str,
    pending: dict[str, object],
    request: DiscographyChoiceRequest,
) -> int:
    body = request.model_dump()
    body["request_id"] = pending.get("request_id")
    return http.post(
        f"/commands/plan-discographies-jobs/{job}/choice", json=body
    ).status_code


@pytest.mark.parametrize("preview", [False, True])
def test_added_exact_editions_reach_final_plan_and_existing_effects(
    discography_http: tuple[TestClient, DiscographyLinkSpotify], preview: bool
) -> None:
    """Mixed link outcomes retain valid additions and require final live approval.

    Args:
        discography_http: Real workers and isolated persistent paths.
        preview: Whether source removals and priority writes must be suppressed.
    """
    http, spotify = discography_http
    job = _start(http, preview)
    first = _pending(http, job)
    assert (
        first["kind"] == "release_review"
        and len(cast(list[object], first["releases"])) == 8
    )
    refs = [
        f"spotify:album:{FIRST_LINK}",
        f"https://open.spotify.com/album/{SECOND_LINK}",
        FIRST_LINK,
        "bad-link",
        MISSING_LINK,
    ]
    request = DiscographyChoiceRequest(
        choice="add",
        release_ids=cast(list[str], first["default_release_ids"]),
        album_references=refs,
    )
    assert _submit(http, job, first, request) == 200
    edited = _pending(http, job)
    assert len(cast(list[object], edited["releases"])) == 10
    assert len(cast(list[object], edited["notices"])) == 5
    selected = cast(list[str], edited["default_release_ids"])
    assert {FIRST_LINK, SECOND_LINK} <= set(selected) and len(selected) == 10
    assert (
        _submit(
            http,
            job,
            edited,
            DiscographyChoiceRequest(choice="select", release_ids=selected),
        )
        == 200
    )
    _finish(http, spotify, job, preview)


def _finish(
    http: TestClient, spotify: DiscographyLinkSpotify, job: str, preview: bool
) -> None:
    if not preview:
        confirmation = _pending(http, job)
        assert confirmation["kind"] == "confirm" and spotify.mutations == []
        assert (
            _submit(http, job, confirmation, DiscographyChoiceRequest(choice="apply"))
            == 200
        )
    result = _wait(http, job, "completed")
    assert (
        result["discography_total_releases"],
        result["discography_days"],
        result["discography_open_slots"],
    ) == (10, 5, 0)
    artists = cast(list[dict[str, object]], result["discography_results"])
    assert {FIRST_LINK, SECOND_LINK} <= set(cast(list[str], artists[0]["release_ids"]))
    assert spotify.album_calls == [FIRST_LINK, SECOND_LINK, MISSING_LINK]
    assert spotify.mutations == (
        []
        if preview
        else [("remove", "newfoundland", "a-marker"), ("remove", "queue3", "a-extra")]
    )
    if not preview:
        row = json.loads(discography.DEFAULT_LOG_PATH.read_text().splitlines()[-1])
        assert {FIRST_LINK, SECOND_LINK} <= {
            item["spotify_id"] for item in row["releases"]
        }


def test_invalid_addition_retains_the_current_unchecked_options(
    discography_http: tuple[TestClient, DiscographyLinkSpotify],
) -> None:
    """A recoverable input error cannot reset operator checklist edits.

    Args:
        discography_http: Real worker and mutable synthetic service.
    """
    http, spotify = discography_http
    job = _start(http)
    first = _pending(http, job)
    selected = cast(list[str], first["default_release_ids"])[1:]
    assert (
        _submit(
            http,
            job,
            first,
            DiscographyChoiceRequest(
                choice="add", release_ids=selected, album_references=["not-album"]
            ),
        )
        == 200
    )
    edited = _pending(http, job)
    assert (
        edited["default_release_ids"] == selected
        and len(cast(list[object], edited["releases"])) == 8
    )
    assert edited["notices"] and spotify.album_calls == []
    assert _submit(http, job, edited, DiscographyChoiceRequest(choice="quit")) == 200
    _wait(http, job, "cancelled")


def test_missing_and_stale_proposals_cannot_submit_another_draft(
    discography_http: tuple[TestClient, DiscographyLinkSpotify],
) -> None:
    """Proposal identities isolate repeat clicks and out-of-date forms.

    Args:
        discography_http: Real locked submission and worker consumption.
    """
    http, spotify = discography_http
    job = _start(http)
    first = _pending(http, job)
    endpoint = f"/commands/plan-discographies-jobs/{job}/choice"
    assert http.post(endpoint, json={"choice": "none"}).status_code == 409
    assert _submit(http, job, first, DiscographyChoiceRequest(choice="add")) == 400
    assert (
        _submit(
            http,
            job,
            first,
            DiscographyChoiceRequest(choice="select", release_ids=["unknown"]),
        )
        == 400
    )
    assert (
        _submit(
            http,
            job,
            first,
            DiscographyChoiceRequest(choice="add", album_references=[FIRST_LINK]),
        )
        == 200
    )
    edited = _pending(http, job)
    assert edited["request_id"] != first["request_id"]
    assert _submit(http, job, first, DiscographyChoiceRequest(choice="none")) == 409
    assert _submit(http, job, edited, DiscographyChoiceRequest(choice="quit")) == 200
    _wait(http, job, "cancelled")
    assert spotify.mutations == []


def test_empty_fetched_catalog_still_offers_manual_additions(
    discography_http: tuple[TestClient, DiscographyLinkSpotify],
) -> None:
    """Catalog emptiness cannot bypass the new interaction.

    Args:
        discography_http: Real worker using an empty first catalog.
    """
    http, spotify = discography_http
    spotify.artist_releases["artist"] = []
    job = _start(http)
    first = _pending(http, job)
    assert first["kind"] == "release_review" and first["releases"] == []
    assert (
        _submit(
            http,
            job,
            first,
            DiscographyChoiceRequest(choice="add", album_references=[FIRST_LINK]),
        )
        == 200
    )
    edited = _pending(http, job)
    assert edited["default_release_ids"] == [FIRST_LINK]
    assert _submit(http, job, edited, DiscographyChoiceRequest(choice="quit")) == 200
    _wait(http, job, "cancelled")
    assert spotify.mutations == []


def test_cancel_overlap_and_final_keep_preserve_marker_authority(
    discography_http: tuple[TestClient, DiscographyLinkSpotify],
) -> None:
    """A pending review can be cancelled, and a completed live plan can keep markers.

    Args:
        discography_http: Real jobs sharing isolated registry and state.
    """
    http, spotify = discography_http
    job = _start(http, False)
    _pending(http, job)
    assert http.post("/commands/plan-discographies").status_code == 409
    assert (
        http.post(f"/commands/plan-discographies-jobs/{job}/cancel").status_code == 200
    )
    _wait(http, job, "cancelled")
    assert spotify.mutations == []
    following = _start(http, False)
    first = _pending(http, following)
    assert (
        _submit(
            http,
            following,
            first,
            DiscographyChoiceRequest(
                choice="add",
                release_ids=cast(list[str], first["default_release_ids"]),
                album_references=[FIRST_LINK, SECOND_LINK],
            ),
        )
        == 200
    )
    edited = _pending(http, following)
    assert (
        _submit(
            http,
            following,
            edited,
            DiscographyChoiceRequest(
                choice="select",
                release_ids=cast(list[str], edited["default_release_ids"]),
            ),
        )
        == 200
    )
    final = _pending(http, following)
    assert final["kind"] == "confirm"
    assert (
        _submit(http, following, final, DiscographyChoiceRequest(choice="keep")) == 200
    )
    _wait(http, following, "completed")
    assert spotify.mutations == []


def test_cli_adds_multiple_links_and_uses_exact_reviewed_releases(
    discography_http: tuple[TestClient, DiscographyLinkSpotify],
) -> None:
    """The actual terminal reader reaches metadata resolution and final packing.

    Args:
        discography_http: Scoped terminal settings, client and persistence.
    """
    _http, spotify = discography_http
    response = CliRunner().invoke(
        main.app,
        ["plan-discographies", "--dry-run"],
        input=f"a\nspotify:album:{FIRST_LINK}, https://open.spotify.com/album/{SECOND_LINK}\n\n",
    )
    assert response.exit_code == 0, response.output
    assert "Added:" in response.output and "10 releases over 5 days" in response.output
    assert spotify.album_calls == [FIRST_LINK, SECOND_LINK] and spotify.mutations == []
