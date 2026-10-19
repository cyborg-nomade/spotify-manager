"""Concrete Found Art match observations with the original SDK call arguments."""

from dataclasses import dataclass

from spotipy import Spotify

from spotify_manager.domain.history import Scrobble
from spotify_manager.domain.history_matching import SpotifyTrackMatch


@dataclass(frozen=True)
class LegacyRecommendationMatches:
    """Own the original Found Art catalog boundary.

    Args:
        spotify: Caller-owned synchronous Spotify client.
    """

    spotify: Spotify

    def search(self, play: Scrobble) -> tuple[SpotifyTrackMatch, ...]:
        """Observe one original album-free candidate query.

        Args:
            play: Original artist and track title.

        Returns:
            Complete qualified matches in encounter order.
        """
        from spotify_manager.routines.blast_from_past import search_spotify_matches

        return search_spotify_matches(self.spotify, play)

    def liked(self, groups: list[tuple[SpotifyTrackMatch, ...]]) -> set[str]:
        """Observe live liked membership for the original complete batch.

        Args:
            groups: Complete ordered candidate match groups, including empty groups.

        Returns:
            Currently liked marker identities.
        """
        from spotify_manager.routines.blast_from_past import liked_spotify_track_ids

        return liked_spotify_track_ids(self.spotify, groups)
