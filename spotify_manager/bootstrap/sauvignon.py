"""Compose Sauvignon with original clock, settings and caller-owned effects."""

from collections.abc import Callable
from datetime import UTC
from datetime import datetime
from functools import partial
from pathlib import Path

from spotipy import Spotify

from spotify_manager.application.sauvignon_run import SauvignonRun
from spotify_manager.infrastructure.legacy.sauvignon import LegacySauvignon
from spotify_manager.routines import sauvignon as legacy


def _configure_retry_and_clock(
    now: datetime | None, retry: legacy.RetryCall | None, effects: LegacySauvignon
) -> datetime:
    effects.retry = retry or _immediate
    return (now or legacy.datetime.now(UTC)).astimezone(UTC)


def _immediate(operation: Callable[[], object], description: str) -> object:
    return operation()


def _progress(callback: legacy.ProgressCallback | None, message: str) -> None:
    if callback is not None:
        callback(message)


def sauvignon_workflow(
    spotify: Spotify,
    lastfm: legacy.LastFmReader,
    playlist_id: str,
    choice: legacy.AlbumChoiceReader | None,
    echo: legacy.Echo,
    progress: legacy.ProgressCallback | None,
    retry: legacy.RetryCall | None,
    export_path: Path,
    recent_path: Path,
    cache_path: Path,
    log_path: Path,
    now: datetime | None,
) -> SauvignonRun:
    """Construct one workflow with invocation-owned clients and callbacks.

    Args:
        spotify: Caller-owned Spotify client.
        lastfm: Caller-owned history source.
        playlist_id: Destination identity.
        choice: Edition interaction owned by this invocation.
        echo: Accepted-effect presenter.
        progress: Stage observer.
        retry: Retry policy configured after request validation.
        export_path: Canonical history location.
        recent_path: Recent history location.
        cache_path: Neighborhood cache location.
        log_path: Audit location.
        now: Optional UTC timestamp, observed after validation.

    Returns:
        A workflow whose construction performs no observations or effects.
    """
    from spotify_manager.infrastructure.recommendation_calendar import (
        listening_week_start,
    )

    effects = LegacySauvignon(
        spotify,
        lastfm,
        playlist_id,
        choice,
        _immediate,
        export_path,
        recent_path,
        cache_path,
        log_path,
        progress,
    )
    return SauvignonRun(
        effects,
        partial(_configure_retry_and_clock, now, retry, effects),
        listening_week_start,
        partial(_progress, progress),
        echo,
        legacy.DEFAULT_MAX_PLAYLIST_LENGTH,
        legacy.found_art.MIN_WEEKLY_CANDIDATE_POOL,
        legacy.found_art.WEEKLY_CANDIDATE_POOL_MULTIPLIER,
        legacy.MIN_SPOTIFY_CANDIDATES,
        legacy.SPOTIFY_CANDIDATE_MULTIPLIER,
    )
