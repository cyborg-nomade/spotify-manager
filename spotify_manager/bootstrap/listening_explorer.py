"""Construct Listening Explorer storage outside business execution."""

import os
from tempfile import TemporaryDirectory

from spotify_manager.bootstrap.execution import ExecutionRuntime
from spotify_manager.bootstrap.library_data import get_library_data_service
from spotify_manager.infrastructure.listening.album_tracklists import (
    SpotifyAlbumTracklists,
)
from spotify_manager.infrastructure.listening.library_runtime import LibraryRuntime
from spotify_manager.infrastructure.listening.playlist_gateway import (
    SpotifyPlaylistGateway,
)
from spotify_manager.infrastructure.listening.runtime import ListeningRuntime


def listening_explorer_runtime() -> ListeningRuntime:
    """Create a process-isolated disposable cache below an optional configured root.

    Returns:
        Runtime owning its source reads, generations, worker, and temporary directory.
    """
    directory = TemporaryDirectory(
        prefix="spotify-listening-", dir=os.environ.get("LISTENING_CACHE_DIR")
    )
    return ListeningRuntime(get_library_data_service(), directory)


def listening_library_runtime() -> LibraryRuntime:
    """Construct independent current-collection reads outside HTTP execution.

    Returns:
        Owner of immutable publication generations and its background worker.
    """
    return LibraryRuntime(get_library_data_service())


def listening_album_tracklists(runtime: ExecutionRuntime) -> SpotifyAlbumTracklists:
    """Bind read-only album tracks to the existing shared Spotify client.

    Args:
        runtime: Lifespan owner of the authenticated Spotify API client.

    Returns:
        Reader that acquires the client only when album tracks are requested.
    """
    return SpotifyAlbumTracklists(runtime)


def listening_playlist_gateway(runtime: ExecutionRuntime) -> SpotifyPlaylistGateway:
    """Bind the playlist exporter to the lifespan's Spotify connection.

    Args:
        runtime: Owner of the shared client.

    Returns:
        Authenticated playlist read and write authority.
    """
    return SpotifyPlaylistGateway(runtime)
