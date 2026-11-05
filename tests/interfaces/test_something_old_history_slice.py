"""Verify recorded modes through actual workers, shared state and CLI input."""

import json
from collections.abc import Iterator
from dataclasses import replace
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
from spotify_manager.bootstrap.state import get_state_service
from spotify_manager.bootstrap.state import reset_state_service
from spotify_manager.domain.something_old_history import ChoiceLedger
from spotify_manager.domain.something_old_history import choice_identity
from spotify_manager.infrastructure.something_old_choice_schema import (
    SomethingOldChoiceDefinition,
)
from spotify_manager.interfaces.http import jobs
from spotify_manager.interfaces.http.models.something_old import (
    SomethingOldPendingChoice,
)
from spotify_manager.interfaces.requests.something_old import SomethingOldResources
from spotify_manager.routines import scrobble_history
from tests.domain.test_something_old_history import recorded_choice
from tests.infrastructure.test_something_old_choice_storage import audit_row
from tests.interfaces.test_discovery_slice import _wait
from tests.interfaces.test_slow_listening_slice import _stop
from tests.interfaces.test_vertical_slices import _http_client
from tests.routines.test_scrobble_history import FakeLastFm
from tests.support.runtime_resources import provided_lastfm
from tests.support.something_old_catalog import ARTIST_ID
from tests.support.something_old_catalog import OTHER_ARTIST_ID
from tests.support.something_old_catalog import PLAYLIST_ID
from tests.support.something_old_catalog import RELEASE_ID
from tests.support.something_old_catalog import OldChoiceSpotify
from tests.support.something_old_catalog import seed_old_history


@pytest.fixture
def old_history_http(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, OldChoiceSpotify]]:
    """Bind actual stages to isolated state and native-shaped external observations.

    Args:
        monkeypatch: Scoped client and configuration boundaries.

    Yields:
        Real HTTP client and mutable fake Spotify.
    """
    spotify = OldChoiceSpotify()
    seed_old_history(scrobble_history.DEFAULT_SCROBBLES_PATH)
    settings = Mock(
        return_value=SimpleNamespace(
            something_old_new_playlist=PLAYLIST_ID,
            lastfm_api_key="test-key",
            lastfm_username="review",
        )
    )
    monkeypatch.setattr(jobs, "Settings", settings)
    monkeypatch.setattr(main, "Settings", settings)
    monkeypatch.setattr(main, "_native_client", AsyncMock(return_value=spotify))
    monkeypatch.setattr(clients, "LastFmClient", Mock(return_value=FakeLastFm(())))
    monkeypatch.setattr(clients, "AsyncLastFmClient", provided_lastfm)
    monkeypatch.setattr(jobs, "_blast_jobs", {})
    with _http_client(monkeypatch, cast(SpotifyClient, spotify)) as http:
        try:
            yield http, spotify
        finally:
            _stop()


def _start(http: TestClient, preview: bool = False) -> str:
    response = http.post("/commands/something-old", params={"dry_run": preview})
    assert response.status_code == 202, response.text
    return str(response.json()["job_id"])


def _pending(http: TestClient, job: str) -> SomethingOldPendingChoice:
    result = _wait(http, "something-old", job, "waiting")
    return SomethingOldPendingChoice.model_validate(
        result["something_old_pending_choice"]
    )


def _choose(http: TestClient, job: str, choice: str) -> None:
    response = http.post(
        f"/commands/something-old-jobs/{job}/choice", json={"choice": choice}
    )
    assert response.status_code == 200, response.text


def _ledger() -> ChoiceLedger:
    state = get_state_service().namespace(
        "something_old_choices", SomethingOldChoiceDefinition()
    )
    return SomethingOldChoiceDefinition().decode(state.load())


@pytest.mark.parametrize("mode", ["lastfm_top_tracks", "spotify_top_tracks", "album"])
@pytest.mark.parametrize("preview", [False, True])
def test_real_http_choices_record_only_applied_modes_and_survive_fresh_services(
    old_history_http: tuple[TestClient, OldChoiceSpotify], mode: str, preview: bool
) -> None:
    """Real append completion becomes history across new runtime construction.

    Args:
        old_history_http: Actual application with isolated external resources.
        mode: Explicit current operator selection.
        preview: Suppress append, audit and history writes.
    """
    http, spotify = old_history_http
    job = _start(http, preview)
    pending = _pending(http, job)
    assert pending.kind == "mode" and [
        entry.count for entry in pending.previous_modes
    ] == [0, 0, 0]
    _choose(http, job, mode)
    if mode == "album":
        assert _pending(http, job).kind == "album"
        _choose(http, job, RELEASE_ID)
    result = _wait(http, "something-old", job, "completed")
    assert result["something_old_action"] == ("would add" if preview else "added")
    assert len(_ledger().choices) == int(not preview)
    spotify.playlist.clear()
    reset_state_service()
    fresh = _start(http, True)
    previous = _pending(http, fresh)
    used = next(entry for entry in previous.previous_modes if entry.mode == mode)
    assert used.count == int(not preview)
    assert len(http.get("/commands/something-old-jobs").json()) == 1
    _choose(http, fresh, "quit")
    _wait(http, "something-old", fresh, "cancelled")
    assert len(_ledger().choices) == int(not preview)


def test_real_http_recovers_accepted_append_response_without_duplicate_writes(
    old_history_http: tuple[TestClient, OldChoiceSpotify],
) -> None:
    """A restarted job reconciles full membership before the nonempty early return.

    Args:
        old_history_http: Real worker and mutable Spotify response boundary.
    """
    http, spotify = old_history_http
    spotify.fail_after_append = True
    job = _start(http)
    _pending(http, job)
    _choose(http, job, "spotify_top_tracks")
    _wait(http, "something-old", job, "failed")
    assert _ledger().choices == {} and _ledger().pending
    reset_state_service()
    resumed = _start(http)
    result = _wait(http, "something-old", resumed, "completed")
    assert result["something_old_action"] == "playlist not empty"
    assert len(_ledger().choices) == 1 and _ledger().pending == {}
    assert next(iter(_ledger().choices.values())).provenance == "recovered"
    assert len(spotify.writes) == 1


def test_real_audit_import_is_visible_and_never_merged_by_artist_name(
    old_history_http: tuple[TestClient, OldChoiceSpotify],
) -> None:
    """A same-name different Spotify identity shows only its own recorded choices.

    Args:
        old_history_http: Isolated actual audit, mapping and mode-selection flow.
    """
    http, spotify = old_history_http
    choice = replace(
        recorded_choice(),
        artist_id=ARTIST_ID,
        artist_name="Old Artist",
        lastfm_artist="Old Artist",
    )
    SomethingOldResources().log_path.write_text(json.dumps(audit_row(choice)) + "\n")
    job = _start(http, True)
    pending = _pending(http, job)
    assert (
        pending.previous_modes[1].count == 1
        and pending.previous_modes[1].provenance == "audit"
    )
    assert _ledger().choices == {}
    _choose(http, job, "quit")
    _wait(http, "something-old", job, "cancelled")
    spotify.ambiguous = True
    second = _start(http)
    assert _pending(http, second).kind == "artist"
    _choose(http, second, OTHER_ARTIST_ID)
    assert all(entry.count == 0 for entry in _pending(http, second).previous_modes)
    _choose(http, second, "quit")
    _wait(http, "something-old", second, "cancelled")
    assert len(_ledger().choices) == 1 and not spotify.writes


def test_cli_shows_previous_choices_without_using_them_as_the_current_answer(
    old_history_http: tuple[TestClient, OldChoiceSpotify],
) -> None:
    """The original prompt remains explicit beside per-mode count/date evidence.

    Args:
        old_history_http: Actual CLI composition and isolated durable history.
    """
    _http, spotify = old_history_http
    choice = replace(recorded_choice(), artist_id=ARTIST_ID, artist_name="Old Artist")
    namespace = get_state_service().namespace(
        "something_old_choices", SomethingOldChoiceDefinition()
    )
    namespace.load()
    namespace.save(
        SomethingOldChoiceDefinition().encode(
            ChoiceLedger(choices={choice_identity(choice): choice})
        )
    )
    result = CliRunner().invoke(main.app, ["something-old", "--dry-run"], input="q\n")
    assert result.exit_code == 0, result.output
    assert "Previously chosen" in result.output and "Chosen 1 time" in result.output
    assert (
        "Most recent recorded choice" in result.output
        and "No recorded use" in result.output
    )
    assert not spotify.writes and len(_ledger().choices) == 1


@pytest.mark.parametrize("kind", ["mode", "album"])
def test_cancelled_real_jobs_never_enter_completed_choice_history(
    old_history_http: tuple[TestClient, OldChoiceSpotify],
    kind: str,
) -> None:
    """Waiting prompts reconnect with stable evidence and cancellation adds no event.

    Args:
        old_history_http: Real HTTP lifecycle with isolated namespace.
        kind: Mode or release interaction to abandon.
    """
    http, spotify = old_history_http
    job = _start(http)
    pending = _pending(http, job)
    active = http.get("/commands/something-old-jobs").json()
    assert active[0]["something_old_pending_choice"] == pending.model_dump()
    assert http.post("/commands/something-old").status_code == 409
    if kind == "album":
        _choose(http, job, "album")
        assert _pending(http, job).kind == "album"
    response = http.post(f"/commands/something-old-jobs/{job}/cancel")
    assert response.status_code == 200
    _wait(http, "something-old", job, "cancelled")
    assert not spotify.writes and _ledger().choices == {} and _ledger().pending == {}
