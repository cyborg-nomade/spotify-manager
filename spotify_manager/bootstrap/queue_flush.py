"""Compose restartable Queue flush with caller-owned original boundaries."""

from pathlib import Path

from spotipy import Spotify

from spotify_manager.application.queue_flush import QueueFlush
from spotify_manager.application.queue_flush_values import FlushSummary
from spotify_manager.core.state.service import StateService
from spotify_manager.infrastructure.legacy.queue_flush import LegacyQueueFlush
from spotify_manager.routines import the_queue as legacy


def flush_queue(
    spotify: Spotify,
    playlists: legacy.QueuePlaylists,
    preview: bool,
    echo: legacy.Echo,
    progress: legacy.ProgressCallback | None,
    retry: legacy.RetryCall | None,
    state_path: Path,
    state_service: StateService | None,
    log_path: Path,
    artists_path: Path,
) -> FlushSummary:
    """Bind the original retry, state, SDK, mirror and presentation seams.

    Args:
        spotify: Original caller-owned Spotify client.
        playlists: Original configured destination identities.
        preview: Original preview behavior.
        echo: Original text presenter.
        progress: Original optional status presenter.
        retry: Original optional retry boundary.
        state_path: Original state location.
        state_service: Original optional shared state authority.
        log_path: Original audit location.
        artists_path: Original artist mirror location.

    Returns:
        Original complete ordered flush outcome.
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
    return QueueFlush(edge).run(preview)
