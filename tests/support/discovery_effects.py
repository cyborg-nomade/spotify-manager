"""In-memory discovery effects with explicit failure and ordering observations."""

from copy import deepcopy
from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import datetime
from datetime import timedelta

from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.discovery import CatalogTrack
from spotify_manager.domain.discovery import RankedRelease
from spotify_manager.models.lookups import AlbumEvaluation


@dataclass
class MemoryLibrary:
    """Observe effects and fail at a selected external boundary.

    Args:
        is_saved: Current remote membership.
        fail_at: Optional effect that fails before changing remote membership.
        events: Ordered effect observations.
    """

    is_saved: bool = False
    fail_at: str | None = None
    events: list[tuple[str, object]] = field(default_factory=list)

    def _record(self, name: str, value: object) -> None:
        self.events.append((name, value))
        if self.fail_at == name:
            raise OSError(name)

    def saved(self, release: RankedRelease) -> bool:
        """Record the membership read and return the current remote state."""
        self._record("saved", release)
        return self.is_saved

    def save_album(self, release: RankedRelease) -> None:
        """Accept a remote save after its failure boundary."""
        self._record("save", release)
        self.is_saved = True

    def remove_album(self, release: RankedRelease) -> None:
        """Accept a remote removal after its failure boundary."""
        self._record("remove", release)
        self.is_saved = False

    def removed_audit(
        self, release: RankedRelease, evaluation: AlbumEvaluation
    ) -> None:
        """Record recovery details before mirror reconciliation."""
        self._record("recovery", (release, evaluation))

    def mirror(self, release: RankedRelease, should_save: bool) -> None:
        """Record the desired mirror membership even without a remote change."""
        self._record("mirror", (release, should_save))

    def event(self, name: str, **details: object) -> None:
        """Record original routine event fields in insertion order."""
        self._record("audit", (name, details))

    def reconciled(
        self,
        release: RankedRelease,
        evaluation: AlbumEvaluation,
        action: str,
        dry_run: bool,
    ) -> None:
        """Record presentation after routine audit success."""
        self._record("message", (release, evaluation, action, dry_run))


@dataclass
class MemoryEffects(MemoryLibrary):
    """Observe ordered review effects, accepted memberships and clock boundaries.

    Args:
        great: Resolved Great Discoveries playlist, absent for creation previews.
        destinations: Observed destination artist and track memberships.
        following: Live follow membership.
        remote_ids: Accepted remote playlist track memberships.
        clock_reads: Number of accepted clock observations.
    """

    great: str | None = "great"
    destinations: dict[str, tuple[set[str], set[str]]] = field(default_factory=dict)
    following: bool = True
    remote_ids: dict[str, set[str]] = field(default_factory=dict)
    clock_reads: int = 0

    def append(self, playlist_id: str, track: CatalogTrack, description: str) -> None:
        """Accept a remote marker append after its failure boundary."""
        self._record("append", (playlist_id, track, description))
        self.remote_ids.setdefault(playlist_id, set()).add(track.spotify_id)

    def remove(self, playlist_id: str, source: PlaylistTrack, label: str) -> None:
        """Accept remote source removal after its failure boundary."""
        self._record("remove_source", (playlist_id, source, label))
        self.remote_ids.setdefault(playlist_id, set()).discard(source.spotify_id)

    def membership(self, playlist_id: str) -> tuple[set[str], set[str]]:
        """Read uncached live destination artist and track memberships."""
        self._record("membership", playlist_id)
        artists, tracks = self.destinations.get(playlist_id, (set(), set()))
        return set(artists), set(tracks)

    def great_playlist(self, state: dict[str, object], dry_run: bool) -> str | None:
        """Record the existing destination resolver boundary."""
        self._record("great", (deepcopy(state), dry_run))
        return self.great

    def followed(self, artist_id: str, artist_name: str) -> bool:
        """Observe current follow membership before any unfollow effect."""
        self._record("followed", (artist_id, artist_name))
        return self.following

    def unfollow(self, artist_id: str, artist_name: str) -> None:
        """Accept remote unfollowing after its failure boundary."""
        self._record("unfollow", (artist_id, artist_name))
        self.following = False

    def remove_local_artist(self, artist_id: str) -> None:
        """Record canonical artist-mirror removal after successful unfollowing."""
        self._record("artist_mirror", artist_id)

    def load(self) -> dict[str, object]:
        """Reject unexpected reads from the execution-only checkpoint boundary."""
        raise AssertionError("Execution must not reload the namespace")

    def save(self, value: dict[str, object], *, message: str | None = None) -> None:
        """Snapshot the complete namespace at the accepted checkpoint boundary."""
        self._record("checkpoint", (deepcopy(value), message))

    def clock(self) -> datetime:
        """Return distinct UTC seconds to expose artist/composer timestamp ordering."""
        value = datetime(2026, 9, 27, tzinfo=UTC) + timedelta(seconds=self.clock_reads)
        self.clock_reads += 1
        return value

    def marker_added(self, name: str, dry_run: bool) -> None:
        """Record replacement presentation after live projection changes."""
        self._record("marker_added", (name, dry_run))

    def marker_removed(self, name: str, dry_run: bool) -> None:
        """Record removal presentation only for a previously present source."""
        self._record("marker_removed", (name, dry_run))

    def artist_added(self, name: str, label: str, dry_run: bool) -> None:
        """Record promotion presentation after destination projection changes."""
        self._record("artist_added", (name, label, dry_run))

    def future_artist_added(self, name: str, label: str, track: str) -> None:
        """Record preview promotion without querying nonexistent membership."""
        self._record("future_artist_added", (name, label, track))

    def artist_unfollowed(self, name: str, dry_run: bool) -> None:
        """Record unfollow presentation after remote and local effects."""
        self._record("artist_unfollowed", (name, dry_run))

    def stale_plan(self, artist: str) -> None:
        """Observe stale plan removal before checkpoint.

        Args:
            artist: Logical artist display name.
        """
        self._record("stale", artist)

    def skipped(self, artist: str) -> None:
        """Observe composer skip after checkpoint.

        Args:
            artist: Logical artist display name.
        """
        self._record("skipped", artist)

    def progress(self, done: int, total: int, message: str) -> None:
        """Observe original progress callback boundaries.

        Args:
            done: Accepted completed-entry count.
            total: Original snapshot size.
            message: Original progress description.
        """
        self._record("progress", (done, total, message))


@dataclass
class MemoryQueue(MemoryLibrary):
    """Observe queue transfer effects with failures before accepted mutations.

    Args:
        queued: Original live queue observations.
    """

    queued: tuple[PlaylistTrack, ...] = field(default_factory=tuple)

    def playlist(self, playlist_id: str) -> tuple[PlaylistTrack, ...]:
        """Observe source queue markers.

        Args:
            playlist_id: Queue source identifier.

        Returns:
            Configured original queue order.
        """
        self._record("playlist", playlist_id)
        return self.queued

    def append(self, playlist_id: str, source: PlaylistTrack, description: str) -> None:
        """Observe destination append before queue removal.

        Args:
            playlist_id: Destination identifier.
            source: Original queue marker.
            description: Original retry message.
        """
        self._record("append", (playlist_id, source, description))

    def remove(self, playlist_id: str, source: PlaylistTrack, description: str) -> None:
        """Observe queue removal before destination projection changes.

        Args:
            playlist_id: Queue source identifier.
            source: Original queue marker.
            description: Original retry message.
        """
        self._record("remove", (playlist_id, source, description))

    def moved(self, artist: str, dry_run: bool) -> None:
        """Observe transfer presentation after routine audit.

        Args:
            artist: Logical artist display name.
            dry_run: Whether to use preview wording.
        """
        self._record("moved", (artist, dry_run))
