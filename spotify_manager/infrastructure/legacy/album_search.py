"""Read original eligible album editions without owning recommendation policy."""

from dataclasses import dataclass

from spotipy import Spotify

from spotify_manager.application.ports.listening import RetryCall
from spotify_manager.domain.album_recommendations import SpotifyAlbumOption
from spotify_manager.domain.recommendation_candidates import FoundArtCandidate


@dataclass(frozen=True)
class LegacyAlbumSearch:
    """Own the client and retry boundary of one album search.

    Args:
        spotify: Caller-owned Spotify client.
        retry: Original retry and cancellation policy.
    """

    spotify: Spotify
    retry: RetryCall

    def search(self, candidate: FoundArtCandidate) -> tuple[SpotifyAlbumOption, ...]:
        """Read original catalog options for one candidate.

        Args:
            candidate: Ranked track evidence.

        Returns:
            Eligible editions in original search order.
        """
        from spotify_manager.routines.sauvignon import search_candidate_albums

        return search_candidate_albums(self.spotify, candidate, self.retry)
