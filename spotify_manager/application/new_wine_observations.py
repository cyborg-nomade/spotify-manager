"""Run-scoped New Wine catalog and membership observations."""

from dataclasses import dataclass
from dataclasses import field
from typing import Protocol

from spotify_manager.domain.catalog import ReleaseCandidate
from spotify_manager.domain.catalog import ReleaseTrack


class WineCatalog(Protocol):
    """Gather current release facts using the original synchronous read boundaries."""

    def tracks(self, release: ReleaseCandidate) -> tuple[ReleaseTrack, ...]:
        """Read a release's ordered playable tracks.

        Args:
            release: Selected release.

        Returns:
            Tracks in original disc and track order.
        """

    def releases(self, artist_id: str, year: int) -> tuple[ReleaseCandidate, ...]:
        """Read current-year primary-credit candidates.

        Args:
            artist_id: Source marker's primary artist.
            year: Existing active year for this invocation.

        Returns:
            Eligible releases in original order.
        """

    def likes(self, ids: list[str], cache: dict[str, bool]) -> None:
        """Fill missing membership observations using the existing batch rules.

        Args:
            ids: Ordered requested track IDs.
            cache: Run-scoped statuses updated by the adapter.
        """


@dataclass
class WineObservations:
    """Reuse only reads whose original implementation already cached within a run.

    Args:
        catalog: Explicit catalog and membership boundary.
        year: Active year selected before the initial playlist reads.
        liked: Previously observed liked statuses.
        release_tracks: Observed playable tracks keyed by release ID.
        artist_releases: Observed current-year candidates keyed by artist ID.
    """

    catalog: WineCatalog
    year: int
    liked: dict[str, bool] = field(default_factory=dict)
    release_tracks: dict[str, tuple[ReleaseTrack, ...]] = field(default_factory=dict)
    artist_releases: dict[str, tuple[ReleaseCandidate, ...]] = field(
        default_factory=dict
    )

    def tracks(self, release: ReleaseCandidate) -> tuple[ReleaseTrack, ...]:
        """Observe a release once per invocation, including empty responses.

        Args:
            release: Release whose tracks are needed now.

        Returns:
            Cached or newly observed tracks.
        """
        if release.spotify_id not in self.release_tracks:
            self.release_tracks[release.spotify_id] = self.catalog.tracks(release)
        return self.release_tracks[release.spotify_id]

    def releases(self, artist_id: str) -> tuple[ReleaseCandidate, ...]:
        """Observe an artist's current-year releases once per invocation.

        Args:
            artist_id: Primary artist to observe.

        Returns:
            Cached or newly observed candidates.
        """
        if artist_id not in self.artist_releases:
            self.artist_releases[artist_id] = self.catalog.releases(
                artist_id, self.year
            )
        return self.artist_releases[artist_id]

    def memberships(self, tracks: tuple[ReleaseTrack, ...]) -> None:
        """Observe missing likes for the supplied canonical track sequence.

        Args:
            tracks: Ordered tracks needed for this decision.
        """
        self.catalog.likes([track.spotify_id for track in tracks], self.liked)

    def source_liked(self, spotify_id: str) -> bool:
        """Observe the current source before reconstructing its preceding streak.

        Args:
            spotify_id: Original marker ID.

        Returns:
            Current source status under the existing per-run cache policy.
        """
        self.catalog.likes([spotify_id], self.liked)
        return self.liked[spotify_id]
