"""Read original complete release tracks for containing-record decisions."""

from dataclasses import dataclass

from spotify_manager.application.ports.listening import RetryCall
from spotify_manager.application.ports.spotify_client import SpotifyClient as Spotify
from spotify_manager.domain.release_check_values import ReleaseCandidate
from spotify_manager.domain.release_check_values import ReleaseTrack


@dataclass(frozen=True)
class LegacyReleaseTracks:
    """Retain the caller's client and retry policy for one catalog.

    Args:
        spotify: Original synchronous Spotify client.
        retry: Original request retry policy.
    """

    spotify: Spotify
    retry: RetryCall

    async def read(self, release: ReleaseCandidate) -> tuple[ReleaseTrack, ...]:
        """Observe the original complete track list.

        Args:
            release: Original announced release.

        Returns:
            Original ordered playable release tracks.
        """
        from spotify_manager.routines.release_check import (
            async_load_release_tracks as load_release_tracks,
        )

        return await load_release_tracks(self.spotify, release, self.retry)
