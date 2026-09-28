"""Pre-extraction Queue 3 annual-import mutation, audit and checkpoint contracts."""

from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import cast

import pytest
from spotipy import Spotify

from spotify_manager.routines import new_wine
from spotify_manager.routines import queue_3
from tests.routines.test_queue_3 import FakeSpotify
from tests.routines.test_queue_3 import raw_release
from tests.routines.test_queue_3 import raw_track


@dataclass
class ImportBoundaries:
    """Record external boundaries and fail before the selected accepted operation.

    Args:
        failure: Optional request/audit/checkpoint/message boundary to interrupt.
        events: Original accepted effect observations.
    """

    failure: str | None = None
    events: list[tuple[str, object]] = field(default_factory=list)

    def _record(self, name: str, value: object) -> None:
        self.events.append((name, value))
        if name == self.failure:
            raise OSError(name)

    def retry(self, operation: Callable[[], object], description: str) -> object:
        """Observe request boundaries before executing the simulated Spotify call.

        Args:
            operation: Original SDK or batch operation.
            description: Original retry message.

        Returns:
            Original simulated response.
        """
        name = "add" if description.startswith("importing") else "read"
        self._record(name, description)
        return operation()

    def audit(self, path: Path, event_type: str, **details: object) -> None:
        """Observe audit fields before any working-list extension.

        Args:
            path: Original audit destination.
            event_type: Original event identifier.
            details: Original structured fields.
        """
        self._record("audit", (event_type, details))

    def load(self) -> dict[str, object]:
        """Reject unexpected state reads inside an already prepared import."""
        raise AssertionError("Unexpected namespace load")

    def save(self, value: dict[str, object], *, message: str | None = None) -> None:
        """Observe the complete accepted namespace at its original checkpoint.

        Args:
            value: Complete namespace with import completion set.
            message: Existing optional store message.
        """
        self._record("checkpoint", deepcopy(value))

    def echo(self, message: str) -> None:
        """Observe the summary only after all required effects succeed.

        Args:
            message: Original import summary text.
        """
        self._record("message", message)


def _spotify() -> FakeSpotify:
    spotify = FakeSpotify()
    album = raw_release("album", "Album", artist_id="artist")
    first = raw_track("first", "First", album, artist_id="artist")
    duplicate = raw_track("duplicate", "Duplicate", album, artist_id="artist")
    other = raw_track("other", "Other", album, artist_id="other", artist_name="Other")
    spotify.playlists["great-2025"] = [first, duplicate, other]
    return spotify


def _run(
    spotify: FakeSpotify,
    boundaries: ImportBoundaries,
    state: dict[str, object],
    current: list[new_wine.PlaylistTrack],
    *,
    preview: bool = False,
) -> tuple[list[new_wine.PlaylistTrack], tuple[queue_3.AnnualImportResult, ...]]:
    return queue_3._annual_import(
        cast(Spotify, spotify),
        "queue3",
        current,
        state,
        owned_playlists=(
            queue_3.OwnedPlaylist("great-2025", "Great Discoveries 2025", 3),
        ),
        active_year=2026,
        dry_run=preview,
        retry_call=boundaries.retry,
        log_path=Path("audit.jsonl"),
        echo=boundaries.echo,
        state_access=boundaries,
    )


@pytest.mark.parametrize("preview", [False, True])
def test_original_annual_import_batches_before_all_audits_and_checkpoint(
    monkeypatch: pytest.MonkeyPatch, preview: bool
) -> None:
    """Distinct source artists are audited after additions and before acknowledgment.

    Args:
        monkeypatch: Scoped audit boundary substitution.
        preview: Whether remote writes and checkpoints are suppressed.
    """
    spotify = _spotify()
    boundaries = ImportBoundaries()
    monkeypatch.setattr(queue_3, "append_event", boundaries.audit)
    state: dict[str, object] = {"annual_imports": {}}
    current: list[new_wine.PlaylistTrack] = []
    updated, results = _run(spotify, boundaries, state, current, preview=preview)
    assert updated is current and [track.spotify_id for track in current] == [
        "first",
        "other",
    ]
    assert [result.action for result in results] == (
        ["would add"] * 2 if preview else ["added"] * 2
    )
    expected = (
        ["read", "audit", "audit", "message"]
        if preview
        else ["read", "add", "audit", "audit", "checkpoint", "message"]
    )
    assert [name for name, value in boundaries.events] == expected
    assert spotify.mutations == (
        [] if preview else [("add", "first"), ("add", "other")]
    )
    assert state["annual_imports"] == {} if preview else bool(state["annual_imports"])


@pytest.mark.parametrize("failure", ["add", "audit", "checkpoint", "message"])
def test_original_import_failure_keeps_accepted_projection_boundaries(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    """Remote writes precede audits; working state changes precede completion writes.

    Args:
        monkeypatch: Scoped audit boundary substitution.
        failure: Selected external failure boundary.
    """
    spotify = _spotify()
    boundaries = ImportBoundaries(failure)
    monkeypatch.setattr(queue_3, "append_event", boundaries.audit)
    state: dict[str, object] = {"annual_imports": {}}
    current: list[new_wine.PlaylistTrack] = []
    with pytest.raises(OSError, match=failure):
        _run(spotify, boundaries, state, current)
    assert bool(current) == (failure in {"checkpoint", "message"})
    assert bool(state["annual_imports"]) == (failure in {"checkpoint", "message"})
    assert bool(spotify.mutations) == (failure != "add")
    assert boundaries.events[-1][0] == failure


def test_original_completed_import_returns_without_source_lookup_or_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Completed yearly records suppress the whole import even during previews.

    Args:
        monkeypatch: Scoped audit boundary substitution.
    """
    spotify = _spotify()
    boundaries = ImportBoundaries()
    monkeypatch.setattr(queue_3, "append_event", boundaries.audit)
    state: dict[str, object] = {"annual_imports": {"2026": {"completed": "yes"}}}
    current: list[new_wine.PlaylistTrack] = []
    assert _run(spotify, boundaries, state, current, preview=True) == (current, ())
    assert boundaries.events == []


def _unreadable_source(
    sp: Spotify, playlist_id: str, retry_call: queue_3.RetryCall
) -> tuple[new_wine.PlaylistTrack, ...]:
    raise new_wine.NewWineError("source unavailable")


def test_import_translates_playlist_failure_without_accepting_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Playlist errors retain their Queue 3 type, message and original cause.

    Args:
        monkeypatch: Scoped playlist-reader substitution.
    """
    monkeypatch.setattr(new_wine, "load_playlist_tracks", _unreadable_source)
    boundaries = ImportBoundaries()
    state: dict[str, object] = {"annual_imports": {}}
    with pytest.raises(queue_3.Queue3Error, match="source unavailable") as error:
        _run(_spotify(), boundaries, state, [])
    assert isinstance(error.value.__cause__, new_wine.NewWineError)
    assert boundaries.events == []
    assert state == {"annual_imports": {}}
