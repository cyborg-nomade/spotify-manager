"""Compose Something Old's workflow with original caller-owned boundary inputs."""

from spotipy import Spotify

from spotify_manager.application.something_old_run import SomethingOld
from spotify_manager.bootstrap.history import history_refresh
from spotify_manager.infrastructure.legacy.something_old_run import LegacySomethingOld
from spotify_manager.interfaces.requests.something_old import SomethingOldCallbacks
from spotify_manager.interfaces.requests.something_old import SomethingOldOptions
from spotify_manager.interfaces.requests.something_old import SomethingOldResources
from spotify_manager.routines import something_old as legacy


def something_old(
    spotify: Spotify,
    lastfm: legacy.LastFmReader,
    options: SomethingOldOptions,
    callbacks: SomethingOldCallbacks,
    resources: SomethingOldResources,
) -> SomethingOld:
    """Build the something old application with invocation-owned inputs.

    Args:
        spotify: Caller-owned spotify.
        lastfm: Caller-owned lastfm.
        options: Caller-owned options.
        callbacks: Caller-owned callbacks.
        resources: Caller-owned resources.

    Returns:
        The configured application workflow.
    """
    edge = LegacySomethingOld(spotify, lastfm, options, callbacks, resources)
    history = history_refresh(
        lastfm,
        resources.export_path,
        resources.legacy_delta_path,
        resources.backup_dir,
        resources.history_log_path,
        None,
        callbacks.progress_callback,
        None,
    )
    return SomethingOld(
        edge, history, options.expected_username, legacy.MIN_ARTIST_SCROBBLES
    )
