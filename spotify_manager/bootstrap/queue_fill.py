"""Compose The Queue's fill workflow with original caller-owned boundaries."""

from datetime import datetime
from pathlib import Path

from spotipy import Spotify

from spotify_manager.application.queue_fill import QueueFill
from spotify_manager.application.queue_fill_values import FillSummary
from spotify_manager.application.queue_fill_values import QueueFillRequest
from spotify_manager.core.state.service import StateService
from spotify_manager.infrastructure.legacy.queue_fill import LegacyQueueFill
from spotify_manager.routines import the_queue as legacy


def fill_queue(
    spotify: Spotify,
    lastfm: legacy.LastFmReader,
    playlists: legacy.QueuePlaylists,
    choice: legacy.ArtistChoiceReader | None,
    request: QueueFillRequest,
    echo: legacy.Echo,
    progress: legacy.ProgressCallback | None,
    retry: legacy.RetryCall | None,
    export_path: Path,
    recent_path: Path,
    state_path: Path,
    state_service: StateService | None,
    cache_path: Path,
    log_path: Path,
    now: datetime | None,
) -> FillSummary:
    """Bind the original synchronous client, storage and presentation behavior.

    Args:
        spotify: Original caller-owned Spotify client.
        lastfm: Original caller-owned Last.fm reader.
        playlists: Original parsed destination identities.
        choice: Original optional interaction reader.
        request: Original fill limits and preview mode.
        echo: Original text presenter.
        progress: Original optional status presenter.
        retry: Original optional retry boundary.
        export_path: Original history export location.
        recent_path: Original recent-history location.
        state_path: Original state location.
        state_service: Original optional shared state authority.
        cache_path: Original neighborhood cache location.
        log_path: Original audit location.
        now: Original optional timestamp.

    Returns:
        Original complete fill summary after accepted effects.
    """
    edge = LegacyQueueFill(
        spotify,
        lastfm,
        playlists,
        choice,
        echo,
        progress,
        retry,
        export_path,
        recent_path,
        state_path,
        state_service,
        cache_path,
        log_path,
        now,
    )
    return QueueFill(
        edge,
        legacy.DEFAULT_COUNT,
        legacy.CANDIDATE_POOL_MULTIPLIER,
        legacy.MIN_CANDIDATE_POOL,
        legacy.TOP_TRACK_LIMIT,
    ).run(request)
