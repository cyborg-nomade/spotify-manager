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
    return legacy.search_spotify_artists(sp, artist, retry, text)


def resolve_artist(
    sp: Spotify,
    artist: RankedArtist,
    reader: legacy.ArtistChoiceReader | None,
    retry: legacy.RetryCall,
) -> SpotifyArtistCandidate | str | None:
    """Retain original catalog retries, mapping controls and custom-query semantics.

    Args:
        sp: Caller-owned Spotify client.
        artist: Original ranked Last.fm evidence.
        reader: Original interaction callback, when present.
        retry: Original retry policy.

    Returns:
        Original mapping, control response or absent noninteractive result.

    Raises:
        ReleaseCheckSpotifyError: Original mapping or interaction is invalid.
    """
    controls = frozenset(
        {legacy.CHOICE_SKIP, legacy.CHOICE_SKIP_ARTIST, legacy.CHOICE_QUIT}
    )
    return ArtistMapping(
        partial(_search, sp, retry), reader, controls, legacy.CHOICE_SEARCH_PREFIX
    ).run(artist)
