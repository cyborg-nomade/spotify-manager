"""Compose Sauvignon with original clock, settings and caller-owned effects."""

from collections.abc import Callable
from datetime import UTC
from datetime import datetime
from functools import partial
from pathlib import Path

from spotipy import Spotify

from spotify_manager.application.sauvignon_run import SauvignonRun
from spotify_manager.application.sauvignon_values import SauvignonSummary
from spotify_manager.infrastructure.legacy.sauvignon import LegacySauvignon
from spotify_manager.routines import sauvignon as legacy


def _clock(now: datetime | None) -> datetime:
    return (now or legacy.datetime.now(UTC)).astimezone(UTC)


def _immediate(operation: Callable[[], object], description: str) -> object:
    return operation()


def _progress(callback: legacy.ProgressCallback | None, message: str) -> None:
    if callback is not None:
        callback(message)


def run_sauvignon(
    spotify: Spotify,
    lastfm: legacy.LastFmReader,
    playlist_id: str,
    choice: legacy.AlbumChoiceReader | None,
    count: int | None,
    maximum: int | None,
    seed_count: int,
    dry_run: bool,
    echo: legacy.Echo,
    progress: legacy.ProgressCallback | None,
    retry: legacy.RetryCall | None,
    export_path: Path,
    recent_path: Path,
    cache_path: Path,
    log_path: Path,
    now: datetime | None,
) -> SauvignonSummary:
    """Bind the independent workflow to original configuration and compatibility seams.

    Args:
        spotify: Caller-owned Spotify client.
        lastfm: Caller-owned history source.
        playlist_id: Original destination.
        choice: Original edition interaction.
        count: Optional explicit additions.
        maximum: Optional destination capacity.
        seed_count: Requested seeds.
        dry_run: Original preview mode.
        echo: Original accepted-effect presentation.
        progress: Original progress observer.
        retry: Original retry policy or immediate default.
        export_path: Canonical history location.
        recent_path: Recent history location.
        cache_path: Neighborhood cache location.
        log_path: Audit location.
        now: Optional effective UTC time.

    Returns:
        Original completed result after its audit succeeds.

    Raises:
        SauvignonError: Original request, catalog or storage failure.
    """
    effects = LegacySauvignon(
        spotify,
        lastfm,
        playlist_id,
        choice,
        retry or _immediate,
        export_path,
        recent_path,
        cache_path,
        log_path,
        progress,
    )
    workflow = SauvignonRun(
        effects,
        partial(_clock, now),
        legacy.found_art.listening_week_start,
        partial(_progress, progress),
        echo,
        legacy.DEFAULT_MAX_PLAYLIST_LENGTH,
        legacy.found_art.MIN_WEEKLY_CANDIDATE_POOL,
        legacy.found_art.WEEKLY_CANDIDATE_POOL_MULTIPLIER,
        legacy.MIN_SPOTIFY_CANDIDATES,
        legacy.SPOTIFY_CANDIDATE_MULTIPLIER,
    )
    return workflow.run(playlist_id, count, maximum, seed_count, dry_run)
