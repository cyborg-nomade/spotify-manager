"""Bind independent artist interaction to the original Spotify search seam."""

from functools import partial

from spotipy import Spotify

from spotify_manager.application.artist_mapping import ArtistMapping
from spotify_manager.domain.artist_mapping import SpotifyArtistCandidate
from spotify_manager.domain.release_check_values import RankedArtist
from spotify_manager.routines import release_check as legacy


def _search(
    sp: Spotify, retry: legacy.RetryCall, artist: RankedArtist, text: str | None
) -> tuple[SpotifyArtistCandidate, ...]:
    from spotify_manager.routines.release_check import search_spotify_artists

    return search_spotify_artists(sp, artist, retry, text)


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
        partial(_search, sp, retry), reader, controls, legacy.CHOICE_SEARCH_PREFIX
    )
