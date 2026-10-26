"""Synchronous history playlist pages with caller-owned retry and cancellation."""

from dataclasses import dataclass

from spotipy import Spotify

from spotify_manager.application.ports.runtime import CancellationState
from spotify_manager.application.ports.runtime import Retry


type RetryCall = Retry


@dataclass(frozen=True)
class SpotifyHistoryPages:
    """Read history playlist facts with the original request boundaries.

    Args:
        spotify: Caller-owned client.
        playlist: Source playlist identity.
        retry: Original transport retry policy.
        cancelled: Optional cancellation observation.
    """

    spotify: Spotify
    playlist: str
    retry: RetryCall
    cancelled: CancellationState | None

    def read(self, offset: int) -> object:
        """Read one raw playlist page.

        Args:
            offset: Raw row offset.

        Returns:
            Unvalidated response.
        """
        from spotify_manager.routines.blast_from_past import _playlist_page

        return _playlist_page(
            self.spotify, self.playlist, self.retry, self.cancelled, offset
        )
