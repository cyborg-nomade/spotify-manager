"""Compose restartable Queue flush with caller-owned original boundaries."""

from pathlib import Path

from spotipy import Spotify

from spotify_manager.application.queue_flush import QueueFlush
from spotify_manager.core.state.service import StateService
from spotify_manager.infrastructure.legacy.queue_flush import LegacyQueueFlush
from spotify_manager.routines import the_queue as legacy


def queue_flush(
    spotify: Spotify,
    playlists: legacy.QueuePlaylists,
    echo: legacy.Echo,
    progress: legacy.ProgressCallback | None,
    retry: legacy.RetryCall | None,
    state_path: Path,
    state_service: StateService | None,
    log_path: Path,
    artists_path: Path,
) -> QueueFlush:
    """Construct the invocation dependencies without executing the use case.

    Args:
        spotify: Original caller-owned Spotify client.
        playlists: Original configured destination identities.
        echo: Original text presenter.
        progress: Original optional status presenter.
        retry: Original optional retry boundary.
        state_path: Original state location.
        state_service: Original optional shared state authority.
        log_path: Original audit location.
        artists_path: Original artist mirror location.

    Returns:
        The configured application dependencies or workflow.
    """
    edge = LegacyQueueFlush(
        spotify,
        playlists,
        echo,
        progress,
        retry,
        state_path,
        state_service,
        log_path,
        artists_path,
    )
    return QueueFlush(edge)
