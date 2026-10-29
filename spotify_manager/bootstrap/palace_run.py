"""Compose Palace's application runner with original caller-owned resources."""

from spotify_manager.application.palace_run import Palace
from spotify_manager.application.ports.runtime import NoRetry
from spotify_manager.application.ports.spotify_client import SpotifyClient as Spotify
from spotify_manager.bootstrap.palace_history import palace_history
from spotify_manager.bootstrap.palace_mirror import saved_mirror
from spotify_manager.infrastructure.legacy.palace_run import LegacyPalace
from spotify_manager.interfaces.requests.palace import PalaceCallbacks
from spotify_manager.interfaces.requests.palace import PalaceOptions
from spotify_manager.interfaces.requests.palace import PalaceResources
from spotify_manager.routines import palace_of_memory as legacy


def palace(
    spotify: Spotify,
    options: PalaceOptions,
    callbacks: PalaceCallbacks,
    resources: PalaceResources,
) -> Palace:
    """Build the palace application with invocation-owned inputs.

    Args:
        spotify: Caller-owned spotify.
        options: Caller-owned options.
        callbacks: Caller-owned callbacks.
        resources: Caller-owned resources.

    Returns:
        The configured application workflow.
    """
    retry = callbacks.retry_call or NoRetry()
    edge = LegacyPalace(spotify, options, callbacks, resources, retry)
    mirror = saved_mirror(
        spotify,
        resources.albums_path,
        resources.album_backups_dir,
        resources.album_refresh_log_path,
        retry,
        callbacks.progress_callback,
    )
    history = palace_history(
        resources.scrobbles_path,
        options.today,
        callbacks.random_index_reader,
        callbacks.progress_callback,
    )
    return Palace(
        edge,
        mirror,
        history,
        legacy.HISTORY_COUNT,
        legacy.ALPHABETICAL_COUNT,
        legacy.ALBUM_MATCH_THRESHOLD,
    )
