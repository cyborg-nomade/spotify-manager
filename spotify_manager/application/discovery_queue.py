"""Queue 2 transfers into New Kids with original deduplication and audit rules."""

from dataclasses import dataclass
from typing import Protocol

from spotify_manager.application.new_kids_state import logical_artist
from spotify_manager.application.new_kids_values import FillResult
from spotify_manager.application.ports.discovery import DiscoveryAudit
from spotify_manager.domain.catalog import PlaylistTrack


type QueueTransferResult = tuple[
    list[PlaylistTrack], tuple[FillResult, ...], list[PlaylistTrack]
]


class DiscoveryQueueAccess(Protocol):
    """Read and mutate queue markers at their original retry boundaries."""

    def playlist(self, playlist_id: str) -> tuple[PlaylistTrack, ...]:
        """Read live queue markers in source order.

        Args:
            playlist_id: Queue source identifier.

        Returns:
            Original playable markers, retaining duplicates.
        """

    def append(self, playlist_id: str, source: PlaylistTrack, description: str) -> None:
        """Secure a source marker in the destination.

        Args:
            playlist_id: Destination identifier.
            source: Original queue marker.
            description: Original retry message.
        """

    def remove(self, playlist_id: str, source: PlaylistTrack, description: str) -> None:
        """Remove a moved or reconciled queue marker.

        Args:
            playlist_id: Queue source identifier.
            source: Original queue marker.
            description: Original retry message, preserving reconciliation wording.
        """


class DiscoveryQueuePresentation(Protocol):
    """Render accepted transfers after their routine audit."""

    def moved(self, artist: str, dry_run: bool) -> None:
        """Show the original New Kids transfer message.

        Args:
            artist: Logical artist display name.
            dry_run: Whether to use preview wording.
        """


@dataclass
class QueueProjection:
    """Original mutable destination sequence and per-transfer membership projections.

    Args:
        tracks: Caller-owned destination list, including existing duplicates.
        ids: Current/projected track identifier set.
        artists: Current/projected logical artist identifier set.
    """

    tracks: list[PlaylistTrack]
    ids: set[str]
    artists: set[str]


def _projection(
    current: list[PlaylistTrack], state: dict[str, object]
) -> QueueProjection:
    ids = {track.spotify_id for track in current}
    artists = {logical_artist(state, track)[0] for track in current}
    return QueueProjection(current, ids, artists)


@dataclass(frozen=True)
class DiscoveryQueueTransfer:
    """Move ordered queue markers while retaining original capacity and resume rules.

    Args:
        access: Live playlist read and mutation boundaries.
        audit: Original routine event sink.
        presentation: Original transfer messages.
        destination: New Kids destination identifier.
        source: Queue 2 source identifier.
        capacity: Original destination marker-count cap.
        dry_run: Whether effects are projected without remote mutation.
    """

    access: DiscoveryQueueAccess
    audit: DiscoveryAudit
    presentation: DiscoveryQueuePresentation
    destination: str
    source: str
    capacity: int
    dry_run: bool

    def move(
        self,
        current: list[PlaylistTrack],
        state: dict[str, object],
        queue: list[PlaylistTrack] | None = None,
    ) -> QueueTransferResult:
        """Fill available capacity and retain unprocessed queue markers in order.

        Args:
            current: Caller-owned destination list, updated in place.
            state: Existing logical composer routes.
            queue: Optional observed queue, including an explicitly empty sequence.

        Returns:
            Original destination list, accepted results and untouched queue suffix.
        """
        queued = list(self.access.playlist(self.source)) if queue is None else queue
        projection = _projection(current, state)
        results: list[FillResult] = []
        for index, marker in enumerate(queued):
            artist_id, artist_name = logical_artist(state, marker)
            if len(current) >= self.capacity:
                return current, tuple(results), queued[index:]
            result = self._transfer(projection, marker, artist_id, artist_name)
            results.append(result)
        return current, tuple(results), []

    def _transfer(
        self,
        projection: QueueProjection,
        marker: PlaylistTrack,
        artist_id: str,
        artist_name: str,
    ) -> FillResult:
        if artist_id in projection.artists:
            self._remove(
                marker, f"removing reconciled Queue 2 marker for {artist_name}"
            )
            return FillResult(artist_name, marker.name, "reconciled")
        if marker.spotify_id not in projection.ids and not self.dry_run:
            self.access.append(
                self.destination, marker, f"adding {artist_name} to New Kids"
            )
        self._remove(marker, f"removing {artist_name} from Queue 2")
        projection.tracks.append(marker)
        projection.ids.add(marker.spotify_id)
        projection.artists.add(artist_id)
        result = FillResult(artist_name, marker.name, "moved")
        self._audit(marker, artist_id, artist_name)
        self.presentation.moved(artist_name, self.dry_run)
        return result

    def _remove(self, marker: PlaylistTrack, description: str) -> None:
        if not self.dry_run:
            self.access.remove(self.source, marker, description)

    def _audit(self, marker: PlaylistTrack, artist_id: str, artist_name: str) -> None:
        self.audit.event(
            "queue_2_moved",
            artist=artist_name,
            artist_id=artist_id,
            track=marker.name,
            track_id=marker.spotify_id,
            dry_run=self.dry_run,
        )
