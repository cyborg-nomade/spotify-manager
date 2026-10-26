"""Named matching, membership and track reads for Golden Oldies recipes."""

from dataclasses import dataclass

from spotipy import Spotify

from spotify_manager.application.ports.runtime import Retry
from spotify_manager.domain.catalog import DiscographyRelease
from spotify_manager.domain.catalog import ReleaseTrack
from spotify_manager.domain.golden_oldies import GoldenOldieArtist
from spotify_manager.domain.golden_oldies import LastFmTrackStat
from spotify_manager.domain.history_matching import SpotifyTrackMatch


type RetryCall = Retry


@dataclass(frozen=True)
class GoldenCatalog:
    """Observe catalog facts through the original synchronous retry boundaries.

    Args:
        spotify: Caller-owned synchronous client.
        retry: Original transport retry policy.
    """

    spotify: Spotify
    retry: RetryCall

    def matches(
        self, artist: GoldenOldieArtist, title: LastFmTrackStat
    ) -> tuple[SpotifyTrackMatch, ...]:
        """Read qualified title matches.

        Args:
            artist: Selected history artist.
            title: Ranked history title.

        Returns:
            Complete candidates.
        """
        from spotify_manager.routines.something_old import _read_lastfm_matches

        return _read_lastfm_matches(self.spotify, artist, self.retry, title)

    def liked(
        self, artist: GoldenOldieArtist, groups: list[tuple[SpotifyTrackMatch, ...]]
    ) -> set[str]:
        """Read membership for all gathered matches.

        Args:
            artist: Selected history artist.
            groups: Complete gathered matches.

        Returns:
            Liked identities.
        """
        from spotify_manager.routines.something_old import _read_lastfm_liked

        return _read_lastfm_liked(self.spotify, artist, self.retry, groups)

    def tracks(self, release: DiscographyRelease) -> tuple[ReleaseTrack, ...]:
        """Read complete tracks for an accepted release.

        Args:
            release: Selected studio release.

        Returns:
            Complete playback-order tracks.
        """
        from spotify_manager.routines.something_old import _read_studio_tracks

        return _read_studio_tracks(self.spotify, self.retry, release)
