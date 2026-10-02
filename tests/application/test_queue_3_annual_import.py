"""Annual import preserves accepted writes, audit ordering and completion boundaries."""

from copy import deepcopy
from dataclasses import dataclass
from dataclasses import field
from dataclasses import replace

import pytest

from spotify_manager.application.queue_3_import import AnnualDiscoveryImport
from spotify_manager.application.queue_3_import import resolve_yearly_playlist
from spotify_manager.application.queue_3_import_review import AnnualImportReview
from spotify_manager.application.queue_3_values import Queue3ConfigError
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.composers import OwnedPlaylist
from tests.support.listening_values import playlist_track
from tests.support.listening_values import studio_release


MARKER = playlist_track("first", studio_release("album", "Album"))
OWNED = (OwnedPlaylist("source", "Great Discoveries 2025", 0),)


@dataclass
class ImportMemory:
    """Observe each boundary and retain only accepted remote and checkpoint effects.

    Args:
        source: Parsed source observations.
        failure: Boundary that fails before acceptance.
        events: Ordered boundary observations.
        remote: Successfully appended markers.
        checkpoint: Last accepted namespace snapshot.
    """

    source: list[PlaylistTrack] = field(default_factory=list)
    failure: str | None = None
    events: list[tuple[str, object]] = field(default_factory=list)
    remote: list[PlaylistTrack] = field(default_factory=list)
    checkpoint: dict[str, object] | None = None

    def _record(self, name: str, value: object) -> None:
        self.events.append((name, value))
        if name == self.failure:
            raise OSError(name)

    def read(self, playlist_id: str) -> list[PlaylistTrack]:
        """Observe a playlist read.

        Args:
            playlist_id: Requested source.

        Returns:
            Configured parsed markers.
        """
        self._record("read", playlist_id)
        return self.source

    def append(
        self, playlist_id: str, tracks: list[PlaylistTrack], description: str
    ) -> None:
        """Accept an append after its failure boundary.

        Args:
            playlist_id: Requested destination.
            tracks: Ordered additions.
            description: Retry description.
        """
        self._record("append", (playlist_id, tracks, description))
        self.remote.extend(tracks)

    def audit(self, event: str, details: dict[str, object]) -> None:
        """Observe the original structured audit.

        Args:
            event: Event identifier.
            details: Original event fields.
        """
        self._record("audit", (event, details))

    def load(self) -> dict[str, object]:
        """Reject unexpected reads of already prepared state.

        Raises:
            AssertionError: Import attempts an unnecessary namespace read.
        """
        raise AssertionError("Unexpected state read")

    def save(self, value: dict[str, object], *, message: str | None = None) -> None:
        """Accept a detached checkpoint after its failure boundary.

        Args:
            value: Complete working namespace.
            message: Optional storage description.
        """
        self._record("checkpoint", value)
        self.checkpoint = deepcopy(value)

    def present(
        self, year: int, additions: int, considered: int, dry_run: bool
    ) -> None:
        """Observe the final summary after all required effects.

        Args:
            year: Source year.
            additions: Added artist count.
            considered: Unique artist count.
            dry_run: Preview flag.
        """
        self._record("message", (year, additions, considered, dry_run))

    def now(self) -> str:
        """Observe the completion timestamp read.

        Returns:
            Fixed checkpoint timestamp.
        """
        self._record("clock", None)
        return "completed-at"


def _service(memory: ImportMemory) -> AnnualDiscoveryImport:
    return AnnualDiscoveryImport(
        memory.read, memory.append, memory.audit, memory, memory.present, memory.now
    )


@pytest.mark.parametrize("preview", [False, True])
def test_import_records_original_fields_and_preserves_namespace(preview: bool) -> None:
    """Mixed existing/new artists retain ordering and original checkpoint fields.

    Args:
        preview: Whether remote writes and checkpoints are suppressed.
    """
    existing = replace(MARKER, primary_artist_id="existing")
    memory = ImportMemory([MARKER, existing, MARKER])
    current = [existing]
    state: dict[str, object] = {"annual_imports": {}, "unknown": "preserved"}
    updated, results = _service(memory).run(
        "queue", current, state, OWNED, 2026, preview
    )
    assert updated is current and current == [existing, MARKER]
    assert [result.action for result in results] == [
        "would add" if preview else "added",
        "already present",
    ]
    assert memory.remote == ([] if preview else [MARKER])
    assert memory.events[-1] == ("message", (2025, 1, 2, preview))
    audits = [value for name, value in memory.events if name == "audit"]
    assert audits[0] == (
        "annual_import_artist",
        {
            "active_year": 2026,
            "source_year": 2025,
            "source_playlist_id": "source",
            "artist": MARKER.primary_artist_name,
            "artist_id": MARKER.primary_artist_id,
            "track": MARKER.name,
            "track_id": "first",
            "action": results[0].action,
            "dry_run": preview,
        },
    )
    assert state["unknown"] == "preserved"
    assert (memory.checkpoint is None) == preview
    expected = (
        {}
        if preview
        else {
            "2026": {
                "completed": True,
                "source_year": 2025,
                "source_playlist_id": "source",
                "completed_at": "completed-at",
                "artists_seen": 2,
                "artists_added": 1,
            }
        }
    )
    assert state["annual_imports"] == expected


@pytest.mark.parametrize("previous", [None, "invalid", {}, {"completed": False}])
def test_empty_source_still_checkpoints_completion(previous: object) -> None:
    """Only a truthy completed record suppresses an annual import.

    Args:
        previous: Incomplete or tolerantly ignored stored value.
    """
    memory = ImportMemory()
    state: dict[str, object] = {"annual_imports": {"2026": previous}}
    assert _service(memory).run("queue", [], state, OWNED, 2026, False) == ([], ())
    assert [name for name, value in memory.events] == [
        "read",
        "clock",
        "checkpoint",
        "message",
    ]
    assert memory.checkpoint is not None


@pytest.mark.parametrize("preview", [False, True])
def test_completed_guard_needs_no_source_or_effects(preview: bool) -> None:
    """A truthy completion flag suppresses source resolution even for a preview.

    Args:
        preview: Whether a preview was requested.
    """
    memory = ImportMemory()
    state: dict[str, object] = {"annual_imports": {"2026": {"completed": "yes"}}}
    current: list[PlaylistTrack] = []
    updated, results = _service(memory).run("queue", current, state, (), 2026, preview)
    assert updated is current and results == ()
    assert memory.events == []


@pytest.mark.parametrize(
    "failure", ["read", "append", "audit", "clock", "checkpoint", "message"]
)
def test_failure_preserves_only_earlier_accepted_effects(failure: str) -> None:
    """Recovery boundaries preserve the original remote/local divergence.

    Args:
        failure: First failing external boundary.
    """
    memory = ImportMemory([MARKER], failure)
    current: list[PlaylistTrack] = []
    state: dict[str, object] = {"annual_imports": {}}
    with pytest.raises(OSError, match=failure):
        _service(memory).run("queue", current, state, OWNED, 2026, False)
    assert bool(memory.remote) == (failure not in {"read", "append"})
    assert bool(current) == (failure in {"clock", "checkpoint", "message"})
    assert bool(state["annual_imports"]) == (failure in {"checkpoint", "message"})
    assert (memory.checkpoint is not None) == (failure == "message")
    assert memory.events[-1][0] == failure


@pytest.mark.parametrize("ids", [(), ("first", "second")])
def test_source_resolution_rejects_missing_and_ambiguous_ids(
    ids: tuple[str, ...],
) -> None:
    """Source configuration fails before reading a playlist.

    Args:
        ids: Missing or ambiguous matching source IDs.
    """
    owned = tuple(OwnedPlaylist(value, "Great Discoveries 2025", 0) for value in ids)
    expected = (
        'Found multiple playlists named "Great Discoveries 2025"; rename the extras '
        "before running Queue 3."
        if ids
        else 'Could not find a playlist named exactly "Great Discoveries 2025".'
    )
    with pytest.raises(Queue3ConfigError) as error:
        resolve_yearly_playlist(owned, 2025)
    assert str(error.value) == expected


def test_memory_rejects_unexpected_namespace_reads() -> None:
    """The test store exposes an explicit failure for accidental duplicate loads."""
    with pytest.raises(AssertionError, match="Unexpected state read"):
        ImportMemory().load()


@dataclass
class ImportReviewMemory(ImportMemory):
    """Observe standalone completion messages alongside accepted import effects."""

    def already_imported(self, year: int) -> None:
        """Observe the saved-completion message.

        Args:
            year: Previous-year source year.
        """
        self._record("already", year)

    def checked(self, year: int, already_completed: bool) -> None:
        """Observe final progress after import or saved completion.

        Args:
            year: Previous-year source year.
            already_completed: Whether saved completion suppressed the import.
        """
        self._record("checked", (year, already_completed))


@pytest.mark.parametrize("preview", [False, True])
@pytest.mark.parametrize("completed", [False, True])
def test_standalone_review_summarizes_existing_and_new_artists(
    preview: bool, completed: bool
) -> None:
    """The standalone review retains its own saved-completion summary contract.

    Args:
        preview: Whether effects are previews.
        completed: Whether import was previously completed.
    """
    memory = ImportReviewMemory([MARKER])
    state: dict[str, object] = {"annual_imports": {"2026": {"completed": completed}}}
    service = AnnualImportReview(_service(memory), memory)
    result = service.run("queue", [MARKER], state, OWNED, 2026, preview)
    assert result.active_year == 2026 and result.source_year == 2025
    assert result.already_completed == completed and result.dry_run == preview
    assert result.additions == 0 and result.already_present == (0 if completed else 1)
    assert memory.events[-1] == ("checked", (2025, completed))
    assert (memory.events[0][0] == "already") == completed


@pytest.mark.parametrize("preview", [False, True])
def test_standalone_review_counts_proposed_and_accepted_additions(
    preview: bool,
) -> None:
    """Preview additions and real additions count identically in the public summary.

    Args:
        preview: Whether effects are previews.
    """
    memory = ImportReviewMemory([MARKER])
    service = AnnualImportReview(_service(memory), memory)
    result = service.run("queue", [], {"annual_imports": {}}, OWNED, 2026, preview)
    assert result.additions == 1 and result.already_present == 0
    assert len(result.results) == 1
