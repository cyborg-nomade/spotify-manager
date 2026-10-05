"""Compose Palace's application runner with original caller-owned resources."""

from spotipy import Spotify

from spotify_manager.application.palace_run import Palace
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
    from spotify_manager.routines.palace_of_memory import _direct_retry

    retry = callbacks.retry_call or _direct_retry
    edge = LegacyPalace(spotify, options, callbacks, resources, retry)
    return Palace(edge, legacy.ALPHABETICAL_COUNT, legacy.ALBUM_MATCH_THRESHOLD)
