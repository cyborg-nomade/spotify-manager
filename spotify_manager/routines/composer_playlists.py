"""Compatibility entry points for shared composer playlist observations."""

from spotipy import Spotify as LegacySpotify

from spotify_manager.application.ports.runtime import Retry
from spotify_manager.application.ports.spotify_client import SpotifyClient as Spotify
from spotify_manager.domain.composers import (
    COMPOSER_PLAYLIST_PREFIX as COMPOSER_PLAYLIST_PREFIX,
)
from spotify_manager.domain.composers import (
    GENERIC_ARTIST_TERMS as GENERIC_ARTIST_TERMS,
)
from spotify_manager.domain.composers import NAME_SUFFIXES as NAME_SUFFIXES
from spotify_manager.domain.composers import (
    SURNAME_PLAYLIST_DESCRIPTORS as SURNAME_PLAYLIST_DESCRIPTORS,
)
from spotify_manager.domain.composers import OwnedPlaylist as OwnedPlaylist
from spotify_manager.domain.composers import (
    composer_playlist_candidates as composer_playlist_candidates,
)
from spotify_manager.domain.composers import (
    is_composer_playlist_candidate as is_composer_playlist_candidate,
)
from spotify_manager.domain.composers import name_tokens as name_tokens
from spotify_manager.infrastructure.python_compat.retry import (
    BlockingRetry as LegacyRetry,
)
from spotify_manager.infrastructure.spotify.composer_playlists import (
    ComposerPlaylistError as ComposerPlaylistError,
)
from spotify_manager.infrastructure.spotify.composer_playlists import (
    SpotifyPlaylistPages,
)
from spotify_manager.infrastructure.spotify.composer_playlists import (
    observe_owned_playlists,
)


type RetryCall = Retry


PLAYLIST_PAGE_LIMIT = 50


async def _playlist_page(sp: Spotify, retry_call: RetryCall, offset: int) -> object:
    for attempt in retry_call.attempts(f"loading owned playlists at offset {offset}"):
        async with attempt:
            response = await sp.current_user_playlists(
                limit=PLAYLIST_PAGE_LIMIT, offset=offset
            )
    return response


async def async_load_owned_playlists(
    sp: Spotify,
    retry_call: RetryCall,
    anchor_playlist_ids: frozenset[str],
) -> tuple[OwnedPlaylist, ...]:
    """Load account-owned playlists using a configured queue as the owner anchor.

    Args:
        sp: Caller-owned synchronous Spotify client.
        retry_call: Existing retry policy and event callback.
        anchor_playlist_ids: Configured queue IDs used to establish ownership.

    Returns:
        Owned playlists in response order, retaining duplicates.

    Raises:
        ComposerPlaylistError: Playlist responses or owner anchors are invalid.
    """
    return await observe_owned_playlists(
        SpotifyPlaylistPages(sp, retry_call), anchor_playlist_ids
    )


def load_owned_playlists(
    sp: LegacySpotify,
    retry_call: RetryCall | LegacyRetry,
    anchor_playlist_ids: frozenset[str],
) -> tuple[OwnedPlaylist, ...]:
    """Load account-owned playlists using a configured queue as the owner anchor.

    Args:
        sp: Caller-owned synchronous Spotify client.
        retry_call: Existing retry policy and event callback.
        anchor_playlist_ids: Configured queue IDs used to establish ownership.

    Returns:
        Owned playlists in response order, retaining duplicates.

    Raises:
        ComposerPlaylistError: Playlist responses or owner anchors are invalid.
    """
    from spotify_manager.bootstrap.execution import run_python
    from spotify_manager.infrastructure.python_compat.retry import PythonRetry
    from spotify_manager.infrastructure.spotify_compat import legacy_spotify

    return run_python(
        async_load_owned_playlists(
            legacy_spotify(sp), PythonRetry(retry_call), anchor_playlist_ids
        )
    )
