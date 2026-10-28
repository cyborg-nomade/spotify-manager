"""Concrete original Spotify artist searches for mapping workflows."""

from dataclasses import dataclass

from spotify_manager.application.ports.listening import RetryCall
from spotify_manager.application.ports.spotify_client import SpotifyClient as Spotify
from spotify_manager.domain.artist_mapping import SpotifyArtistCandidate
from spotify_manager.domain.release_check_values import RankedArtist


@dataclass(frozen=True)
class LegacyArtistSearch:
    """Own one mapping's client and retry boundary.

    Args:
        spotify: Caller-owned Spotify client.
        retry: Original retry and cancellation boundary.
    """

    spotify: Spotify
    retry: RetryCall

    async def search(
        self, artist: RankedArtist, text: str | None
    ) -> tuple[SpotifyArtistCandidate, ...]:
        """Read candidates through the original concrete SDK leaf.

        Args:
            artist: Original ranked Last.fm evidence.
            text: Optional custom query.

        Returns:
            Candidates in original search order.
        """
        from spotify_manager.routines.release_check import (
            async_search_spotify_artists as search_spotify_artists,
        )

        return await search_spotify_artists(self.spotify, artist, self.retry, text)
