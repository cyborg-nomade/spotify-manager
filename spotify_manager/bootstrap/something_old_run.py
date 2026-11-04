"""Compose Something Old's workflow with original caller-owned boundary inputs."""

from spotify_manager.application.golden_selection import GoldenLastfmSelection
from spotify_manager.application.ports.spotify_client import SpotifyClient as Spotify
from spotify_manager.application.something_old_history import SomethingOldChoiceHistory
from spotify_manager.application.something_old_run import SomethingOld
from spotify_manager.bootstrap import manual_matching
from spotify_manager.bootstrap.history import history_refresh
from spotify_manager.bootstrap.state import get_state_service
from spotify_manager.infrastructure.async_state import AsyncRoutineState
from spotify_manager.infrastructure.golden_catalog import GoldenCatalog
from spotify_manager.infrastructure.legacy.something_old_run import LegacySomethingOld
from spotify_manager.infrastructure.something_old_choice_schema import (
    SomethingOldChoiceDefinition,
)
from spotify_manager.infrastructure.something_old_choice_storage import (
    SomethingOldChoiceStorage,
)
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
        edge,
        history,
        options.expected_username,
        legacy.MIN_ARTIST_SCROBBLES,
        GoldenLastfmSelection(
            GoldenCatalog(spotify, callbacks.retry_call),
            legacy.blast_from_past.ALBUM_MATCH_THRESHOLD,
            manual_matching.tracks(spotify, callbacks.matching, callbacks.retry_call),
        ),
        _choice_history(spotify, callbacks, resources),
        callbacks.history_reader,
    )


def _choice_history(
    spotify: Spotify, callbacks: SomethingOldCallbacks, resources: SomethingOldResources
) -> SomethingOldChoiceHistory:
    service = resources.state_service or get_state_service()
    namespace = service.namespace(
        "something_old_choices", SomethingOldChoiceDefinition()
    )
    access = SomethingOldChoiceStorage(
        AsyncRoutineState(namespace), resources.log_path, spotify, callbacks.retry_call
    )
    return SomethingOldChoiceHistory(access, callbacks.cancellation)
