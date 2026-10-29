"""Bind independent artist interaction to the original Spotify search seam."""

from spotify_manager.application.artist_mapping import ArtistMapping
from spotify_manager.application.ports.spotify_client import SpotifyClient as Spotify
from spotify_manager.infrastructure.legacy.artist_search import LegacyArtistSearch
from spotify_manager.routines import release_check as legacy


def artist_mapping(
    sp: Spotify,
    reader: legacy.ArtistChoiceReader | None,
    retry: legacy.RetryCall,
) -> ArtistMapping:
    """Construct artist mapping with caller-owned search and choice dependencies.

    Args:
        sp: Caller-owned synchronous Spotify client.
        reader: Optional artist choice callback.
        retry: Existing retry and cancellation boundary.

    Returns:
        The configured application mapping workflow.
    """
    controls = frozenset(
        {legacy.CHOICE_SKIP, legacy.CHOICE_SKIP_ARTIST, legacy.CHOICE_QUIT}
    )
    return ArtistMapping(
        LegacyArtistSearch(sp, retry), reader, controls, legacy.CHOICE_SEARCH_PREFIX
    )
