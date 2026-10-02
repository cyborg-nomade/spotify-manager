"""Deterministic ordered future-record observations without catalog clients."""

from dataclasses import dataclass
from dataclasses import field

from spotify_manager.domain.release_check_values import ReleaseCandidate
from spotify_manager.domain.release_check_values import ReleaseTrack


@dataclass
class Reads:
    """Return explicit original track pages and record ordered observations.

    Args:
        tracks: Original per-album track observations.
        fail: Album whose read fails before returning.
    """

    tracks: dict[str, tuple[ReleaseTrack, ...]]
    fail: str | None = None
    events: list[str] = field(default_factory=list)

    def read(self, release: ReleaseCandidate) -> tuple[ReleaseTrack, ...]:
        """Read original tracks with a possible failure before cache acceptance.

        Args:
            release: Original announced edition.

        Returns:
            Original ordered album tracks.

        Raises:
            RuntimeError: This is the configured original failing read.
        """
        self.events.append(release.spotify_id)
        if release.spotify_id == self.fail:
            raise RuntimeError(release.spotify_id)
        return self.tracks.get(release.spotify_id, ())
