"""Exercise complete Requeue sequencing without SDKs, files, or runtime fixtures."""

from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import datetime

import pytest

from spotify_manager.application.music import NamedTrack
from spotify_manager.application.requeue import RequeueDependencies
from spotify_manager.application.requeue import flush_requeue
from spotify_manager.application.requeue_result import RequeueForADreamChangedError
from spotify_manager.application.requeue_result import RequeueForADreamSummary
from spotify_manager.domain.catalog import DiscographyRelease
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.catalog import ReleaseTrack
from tests.support.listening_values import playlist_track
from tests.support.listening_values import release_track
from tests.support.listening_values import studio_release


FIRST = studio_release("first", "First")
SECOND = studio_release("second", "Second", "2021")
SOURCE = playlist_track("source", FIRST)
TARGET = playlist_track("target", SECOND)
NOW = datetime(2026, 9, 25, 12, tzinfo=UTC)


@dataclass
class MemoryRequeue:
    """Hold playlist facts and record every externally meaningful boundary.

    Args:
        playlist: Mutable remote playlist simulation.
        releases: Selected discography observations.
        tracks: Ordered successor tracks.
        failure: Boundary to fail once, or None.
        after_acceptance: Whether that fault occurs after the simulated effect.
        changed_head: Optional replacement playlist for the final freshness read.
        reads: Number of playlist reads.
        events: Ordered observations and effect calls.
        audits: Successfully persisted summaries.
    """

    playlist: list[PlaylistTrack] = field(default_factory=list)
    releases: tuple[DiscographyRelease, ...] = (FIRST, SECOND)
    tracks: tuple[ReleaseTrack, ...] = (release_track("target"),)
    failure: str | None = None
    after_acceptance: bool = False
    changed_head: tuple[PlaylistTrack, ...] | None = None
    reads: int = 0
    events: list[tuple[str, object]] = field(default_factory=list)
    audits: list[RequeueForADreamSummary] = field(default_factory=list)

    def _fault(self, operation: str, accepted: bool = False) -> None:
        if self.failure != operation or self.after_acceptance != accepted:
            return
        self.failure = None
        raise RuntimeError(f"{operation} interrupted")

    def sources(self, playlist_id: str) -> tuple[PlaylistTrack, ...]:
        """Read current markers and optionally replace the second observation.

        Args:
            playlist_id: Requested playlist identifier.

        Returns:
            Current ordered markers, or the scripted changed head.

        Raises:
            RuntimeError: The read boundary is scripted to fail.
        """
        self.events.append(("read", playlist_id))
        self._fault("read")
        self.reads += 1
        if self.reads == 2 and self.changed_head is not None:
            return self.changed_head
        return tuple(self.playlist)

    def discography(self, artist_id: str) -> tuple[DiscographyRelease, ...]:
        """Return the scripted eligible releases after recording the request.

        Args:
            artist_id: Source artist identifier.

        Returns:
            The selected catalog observations.

        Raises:
            RuntimeError: Catalog retrieval is scripted to fail.
        """
        self.events.append(("catalog", artist_id))
        self._fault("catalog")
        return self.releases

    def release_tracks(self, release: DiscographyRelease) -> tuple[ReleaseTrack, ...]:
        """Return successor tracks after recording their catalog boundary.

        Args:
            release: Selected successor edition.

        Returns:
            The scripted playable tracks.

        Raises:
            RuntimeError: Track retrieval is scripted to fail.
        """
        self.events.append(("tracks", release.spotify_id))
        self._fault("tracks")
        return self.tracks

    def append(self, playlist_id: str, track: NamedTrack) -> None:
        """Append a replacement, optionally losing the response after acceptance.

        Args:
            playlist_id: Destination playlist.
            track: Replacement marker.

        Raises:
            RuntimeError: The scripted failure occurs before or after acceptance.
        """
        self.events.append(("append", (playlist_id, track.uri)))
        self._fault("append")
        self.playlist.append(TARGET)
        self._fault("append", True)

    def remove(self, playlist_id: str, track: NamedTrack) -> None:
        """Remove matching markers, retaining all other playlist positions.

        Args:
            playlist_id: Source playlist.
            track: Marker to remove.

        Raises:
            RuntimeError: The scripted failure occurs before or after acceptance.
        """
        self.events.append(("remove", (playlist_id, track.uri)))
        self._fault("remove")
        self.playlist = [item for item in self.playlist if item.uri != track.uri]
        self._fault("remove", True)

    def echo(self, message: str) -> None:
        """Record the original mutation message.

        Args:
            message: User-visible message after an accepted effect.
        """
        self.events.append(("echo", message))

    def progress(self, message: str) -> None:
        """Record the original progress and cancellation boundary.

        Args:
            message: User-visible stage description.
        """
        self.events.append(("progress", message))

    def audit(self, summary: RequeueForADreamSummary) -> None:
        """Persist a summary with optional before/after acceptance failure.

        Args:
            summary: Completed outcome to persist.

        Raises:
            RuntimeError: The scripted audit boundary fails.
        """
        self.events.append(("audit", summary.action))
        self._fault("audit")
        self.audits.append(summary)
        self._fault("audit", True)

    def clock(self) -> datetime:
        """Observe the timestamp boundary.

        Returns:
            The fixed result timestamp.
        """
        self.events.append(("clock", NOW))
        return NOW

    def dependencies(self, *, progress: bool = True) -> RequeueDependencies:
        """Bind this memory implementation to all required ports.

        Args:
            progress: Whether the optional progress callback is present.

        Returns:
            Explicit dependencies for one invocation.
        """
        return RequeueDependencies(
            self,
            self,
            self.echo,
            self.progress if progress else None,
            self.audit,
            self.clock,
        )


@pytest.mark.parametrize("dry_run", [False, True])
def test_requeue_keeps_full_stage_and_effect_order(dry_run: bool) -> None:
    """Retain read, decision, recheck, mutation, timestamp, and audit ordering.

    Args:
        dry_run: Whether to suppress the final recheck and all writes.
    """
    memory = MemoryRequeue([SOURCE])
    summary = flush_requeue(memory.dependencies(), "p", dry_run=dry_run)
    expected = ["progress", "read", "progress", "catalog", "progress", "tracks"]
    if not dry_run:
        expected += ["progress", "read", "append", "echo", "remove", "echo"]
    expected += ["clock"] if dry_run else ["clock", "audit"]
    assert [event[0] for event in memory.events] == expected
    assert (summary.action, summary.target_track, summary.recorded_at) == (
        "advance",
        "target",
        NOW,
    )
    assert summary.playlist_length_before == summary.playlist_length_after == 1
    assert memory.playlist == ([SOURCE] if dry_run else [TARGET])


@pytest.mark.parametrize(
    ("playlist", "releases", "tracks", "action", "reason"),
    [
        ([], (FIRST, SECOND), (release_track("target"),), "empty", "playlist is empty"),
        (
            [SOURCE],
            (SECOND,),
            (),
            "skip",
            "current release is not an eligible studio album or EP",
        ),
        ([SOURCE], (FIRST,), (), "drop", "last eligible release"),
        ([SOURCE], (FIRST, SECOND), (), "skip", "next release has no playable tracks"),
    ],
)
@pytest.mark.parametrize("dry_run", [False, True])
def test_noop_skip_and_final_release_contracts(
    playlist: list[PlaylistTrack],
    releases: tuple[DiscographyRelease, ...],
    tracks: tuple[ReleaseTrack, ...],
    action: str,
    reason: str,
    dry_run: bool,
) -> None:
    """Keep empty, skipped, and final-release outcomes and their audit rules.

    Args:
        playlist: Original remote markers.
        releases: Eligible catalog observations.
        tracks: Playable successor observations.
        action: Expected legacy action.
        reason: Expected explanation.
        dry_run: Whether this is a preview.
    """
    memory = MemoryRequeue(list(playlist), releases, tracks)
    summary = flush_requeue(memory.dependencies(progress=False), "p", dry_run=dry_run)
    assert (summary.action, summary.reason) == (action, reason)
    assert len(memory.audits) == int(not dry_run and action != "empty")
    assert memory.reads == (2 if action == "drop" and not dry_run else 1)
    assert not any(event[0] == "append" for event in memory.events)


@pytest.mark.parametrize("head", [(), (TARGET,)])
def test_changed_or_missing_head_prevents_all_writes(
    head: tuple[PlaylistTrack, ...],
) -> None:
    """Stop before any effect when the final read no longer has the source head.

    Args:
        head: Changed playlist returned by the second read.
    """
    memory = MemoryRequeue([SOURCE], changed_head=head)
    with pytest.raises(RequeueForADreamChangedError):
        flush_requeue(memory.dependencies(), "p")
    assert memory.playlist == [SOURCE]
    assert not memory.audits
    assert not any(event[0] in {"append", "remove", "clock"} for event in memory.events)


def test_existing_target_is_not_duplicated() -> None:
    """Use the original playlist duplicate observation before removing the source."""
    memory = MemoryRequeue([SOURCE, TARGET])
    summary = flush_requeue(memory.dependencies(), "p")
    assert summary.target_already_present
    assert summary.playlist_length_after == 1
    assert memory.playlist == [TARGET]
    assert (
        "echo",
        "target is already present; it was not duplicated.",
    ) in memory.events
    assert not any(event[0] == "append" for event in memory.events)


@pytest.mark.parametrize(
    ("boundary", "accepted"),
    [
        ("read", False),
        ("catalog", False),
        ("tracks", False),
        ("append", False),
        ("append", True),
        ("remove", False),
        ("remove", True),
        ("audit", False),
        ("audit", True),
    ],
)
def test_partial_failure_and_restart_keep_existing_semantics(
    boundary: str, accepted: bool
) -> None:
    """Resume from accepted remote effects without inventing durable job state.

    Args:
        boundary: Operation interrupted once.
        accepted: Whether the operation took effect before the failure.
    """
    memory = MemoryRequeue([SOURCE], failure=boundary, after_acceptance=accepted)
    with pytest.raises(RuntimeError, match=f"{boundary} interrupted"):
        flush_requeue(memory.dependencies(), "p")
    after_failure = list(memory.playlist)
    result = flush_requeue(memory.dependencies(), "p")
    if after_failure == [TARGET]:
        assert result.action == "drop"
        assert memory.playlist == []
        return
    assert result.action == "advance"
    assert memory.playlist == [TARGET]
    assert result.target_already_present == (after_failure == [SOURCE, TARGET])
