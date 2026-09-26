"""Typed in-memory boundaries for studio progression and interrupted execution."""

from copy import deepcopy
from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import datetime

from spotify_manager.application.slow_listening import SlowListeningDependencies
from spotify_manager.application.slow_listening_plan import StudioObservations
from spotify_manager.application.slow_listening_values import FlushResult
from spotify_manager.domain.catalog import DiscographyRelease
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.catalog import ReleaseTrack
from tests.support.listening_values import playlist_track
from tests.support.listening_values import release_track
from tests.support.listening_values import studio_release


FIRST = studio_release("first", "First")
SECOND = studio_release("second", "Second", "2021")
SOURCE = playlist_track("source", FIRST)
TARGET = release_track("target")
NOW = datetime(2026, 9, 25, 12, tzinfo=UTC)


def _state() -> dict[str, object]:
    return {"version": 1, "release_orders": {}, "active_run": None}


def _tracks() -> dict[str, tuple[ReleaseTrack, ...]]:
    return {FIRST.spotify_id: (release_track("source"), TARGET), SECOND.spotify_id: ()}


@dataclass
class MemorySlowListening:
    """Hold detached durable state, live markers and scripted operator choices.

    Args:
        live: Mutable simulated remote playlist.
        state: Last successfully accepted namespace checkpoint.
        releases: Selected studio catalog observations.
        release_tracks: Track observations keyed by release identifier.
        choices: Scripted track choices; an empty sequence defaults to advance.
        order_ids: Optional explicit tie-order answer.
        replacement: Optional playlist substituted during completion acknowledgement.
        failure: Boundary to fail once.
        occurrence: Which occurrence of that boundary fails.
        accepted: Whether to fail after accepting the effect.
        events: Ordered calls and their payloads.
        counts: Per-boundary occurrence counts.
        audits: Accepted audit records, including previews.
    """

    live: list[PlaylistTrack] = field(default_factory=list)
    state: dict[str, object] = field(default_factory=_state)
    releases: tuple[DiscographyRelease, ...] = (FIRST, SECOND)
    release_tracks: dict[str, tuple[ReleaseTrack, ...]] = field(default_factory=_tracks)
    choices: list[str] = field(default_factory=list)
    order_ids: tuple[str, ...] | None = None
    replacement: list[PlaylistTrack] | None = None
    failure: str | None = None
    occurrence: int = 1
    accepted: bool = False
    events: list[tuple[str, object]] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    audits: list[FlushResult] = field(default_factory=list)

    def _before(self, name: str, value: object = None) -> None:
        self.events.append((name, deepcopy(value)))
        self.counts[name] = self.counts.get(name, 0) + 1
        self._fault(name, False)

    def _fault(self, name: str, accepted: bool) -> None:
        if (name, accepted, self.counts.get(name)) != (
            self.failure,
            self.accepted,
            self.occurrence,
        ):
            return
        self.failure = None
        raise RuntimeError(f"{name} interrupted")

    def playlist(self) -> tuple[PlaylistTrack, ...]:
        """Read current remote markers.

        Returns:
            Ordered current markers.
        """
        self._before("playlist")
        return tuple(self.live)

    def load_state(self, dry_run: bool) -> dict[str, object]:
        """Detach durable state, or start a fresh preview.

        Args:
            dry_run: Whether to ignore the saved namespace.

        Returns:
            A separate mutable working namespace.
        """
        self._before("load", dry_run)
        return _state() if dry_run else deepcopy(self.state)

    def save(self, state: dict[str, object]) -> None:
        """Accept a complete namespace checkpoint.

        Args:
            state: Current working namespace.

        Raises:
            RuntimeError: A failure is scripted before or after acceptance.
        """
        self._before("save", state)
        self.state = deepcopy(state)
        self._fault("save", True)

    def discography(self, artist_id: str) -> tuple[DiscographyRelease, ...]:
        """Return the scripted selected catalog.

        Args:
            artist_id: Primary artist under review.

        Returns:
            Existing chronological release observations.
        """
        self._before("catalog", artist_id)
        return self.releases

    def tracks(self, release: DiscographyRelease) -> tuple[ReleaseTrack, ...]:
        """Return one scripted release's tracks.

        Args:
            release: Selected studio edition.

        Returns:
            Ordered playable tracks, possibly empty.
        """
        self._before("tracks", release.spotify_id)
        return self.release_tracks.get(release.spotify_id, ())

    def append(self, target: ReleaseTrack) -> None:
        """Append a replacement to the simulated remote playlist.

        Args:
            target: Accepted replacement.

        Raises:
            RuntimeError: A failure is scripted before or after acceptance.
        """
        self._before("append", target.spotify_id)
        self.live.append(playlist_track(target.spotify_id, FIRST))
        self._fault("append", True)

    def remove(self, source: PlaylistTrack) -> None:
        """Remove every marker with the source ID.

        Args:
            source: Original marker.

        Raises:
            RuntimeError: A failure is scripted before or after acceptance.
        """
        self._before("remove", source.spotify_id)
        self.live = [
            track for track in self.live if track.spotify_id != source.spotify_id
        ]
        self._fault("remove", True)

    def audit(self, run_id: str, result: FlushResult) -> None:
        """Accept a completed or previewed result.

        Args:
            run_id: Original run identifier.
            result: Result to append.

        Raises:
            RuntimeError: A failure is scripted before or after acceptance.
        """
        self._before("audit", (run_id, result))
        self.audits.append(result)
        self._fault("audit", True)

    def order(
        self, date: str, releases: tuple[DiscographyRelease, ...]
    ) -> tuple[str, ...]:
        """Choose the scripted tie order or retain the display order.

        Args:
            date: Shared chronology date.
            releases: Complete tie options.

        Returns:
            Scripted IDs or the original display order.
        """
        self._before("order", date)
        if self.order_ids is not None:
            return self.order_ids
        return tuple(release.spotify_id for release in releases)

    def choose(
        self, source: PlaylistTrack, target: ReleaseTrack, release: DiscographyRelease
    ) -> str:
        """Consume one scripted track decision.

        Args:
            source: Original marker.
            target: Candidate successor.
            release: Candidate's selected edition.

        Returns:
            Scripted answer, or advance when no answers remain.
        """
        self._before(
            "choose", (source.spotify_id, target.spotify_id, release.spotify_id)
        )
        return self.choices.pop(0) if self.choices else "advance"

    def complete(self, source: PlaylistTrack) -> None:
        """Acknowledge an artist completion, optionally replacing the live list.

        Args:
            source: Final studio marker.
        """
        self._before("complete", source.spotify_id)
        if self.replacement is not None:
            self.live = list(self.replacement)
        self._fault("complete", True)

    def progress(self, completed: int, total: int, message: str) -> None:
        """Record the original progress/cancellation boundary.

        Args:
            completed: Reported completed entry count.
            total: Original snapshot size.
            message: Original stage label.
        """
        self._before("progress", (completed, total, message))

    def skipped(self, source: PlaylistTrack, result: FlushResult) -> None:
        """Observe skip presentation after its audit.

        Args:
            source: Original marker.
            result: Skip result.
        """
        self._before("skipped", result.reason)

    def added(self, target: ReleaseTrack, release_name: str, dry_run: bool) -> None:
        """Observe presentation after a replacement is secured.

        Args:
            target: Replacement track.
            release_name: Selected release title.
            dry_run: Whether the output describes a preview.
        """
        self._before("added", (target.spotify_id, release_name, dry_run))

    def removed(self, source: PlaylistTrack, dry_run: bool) -> None:
        """Observe removal presentation.

        Args:
            source: Original marker.
            dry_run: Whether the output describes a preview.
        """
        self._before("removed", (source.spotify_id, dry_run))

    def completed(self, source: PlaylistTrack, dry_run: bool) -> None:
        """Observe catalog completion presentation.

        Args:
            source: Original marker.
            dry_run: Whether the output describes a preview.
        """
        self._before("completed", (source.spotify_id, dry_run))

    def resumed(self, source: PlaylistTrack) -> None:
        """Observe presentation of a previously removed source.

        Args:
            source: Original saved marker.
        """
        self._before("resumed", source.spotify_id)

    def clock(self) -> datetime:
        """Read the deterministic UTC clock at an observable boundary.

        Returns:
            Fixed timestamp.
        """
        self._before("clock")
        return NOW

    def dependencies(self, *, progress: bool = True) -> SlowListeningDependencies:
        """Bind fresh run-scoped observations to this persistent fake environment.

        Args:
            progress: Whether to include the optional progress callback.

        Returns:
            Complete SDK-free integrations for one invocation.
        """
        return SlowListeningDependencies(
            self,
            StudioObservations(self),
            self.order,
            self.choose,
            self.complete,
            self,
            self.clock,
            self.progress if progress else None,
        )
