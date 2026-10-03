"""Compose dormant history and catalog policies with original clocks and effects."""

from datetime import date
from functools import partial
from pathlib import Path

from spotipy import Spotify

from spotify_manager.application.dormant_recovery import DormantRecovery
from spotify_manager.application.dormant_tracks import DormantLikedTrack
from spotify_manager.domain.discovery import CatalogTrack
from spotify_manager.infrastructure.legacy.dormant_artists import LegacyDormantRecovery
from spotify_manager.routines import blast_from_past_artists as legacy


def _clock(today: date | None) -> date:
    return today or legacy.datetime.now(legacy.blast_from_past.SCROBBLE_TIMEZONE).date()


def _progress(
    callback: legacy.ProgressCallback | None, done: int, count: int, message: str
) -> None:
    if callback is not None:
        callback(done, count, message)


def _top(
    sp: Spotify, artist_id: str, retry: legacy.RetryCall
) -> tuple[CatalogTrack, ...]:
    from spotify_manager.routines.new_kids import load_top_track_data

    _ranks, tracks = load_top_track_data(sp, artist_id, retry)
    return tracks


def _liked(
    sp: Spotify, retry: legacy.RetryCall, tracks: tuple[CatalogTrack, ...]
) -> dict[str, bool]:
    from spotify_manager.routines.blast_from_past_artists import _liked_statuses

    return _liked_statuses(sp, tracks, retry)


def _populate(
    sp: Spotify, retry: legacy.RetryCall, tracks: tuple[CatalogTrack, ...]
) -> tuple[CatalogTrack, ...]:
    from spotify_manager.routines.blast_from_past_artists import _track_popularities

    return _track_popularities(sp, tracks, retry)


def dormant_tracks(
    sp: Spotify, artist_id: str, retry: legacy.RetryCall
) -> DormantLikedTrack:
    """Construct the invocation dependencies without executing the use case.

    Args:
        sp: Caller-owned Spotify client.
        artist_id: Original mapped identity.
        retry: Original retry policy.

    Returns:
        The configured application dependencies or workflow.
    """
    from spotify_manager.routines.blast_from_past_artists import _catalog_tracks

    workflow = DormantLikedTrack(
        partial(_top, sp, artist_id, retry),
        partial(_liked, sp, retry),
        partial(_catalog_tracks, sp, artist_id, retry),
        partial(_populate, sp, retry),
    )
    return workflow


def dormant_recovery(
    sp: Spotify,
    playlist_id: str,
    path: Path,
    today: date | None,
    echo: legacy.Echo,
    progress: legacy.ProgressCallback | None,
    retry: legacy.RetryCall,
    cancel: legacy.CancelCheck | None,
) -> DormantRecovery:
    """Construct the invocation dependencies without executing the use case.

    Args:
        sp: Caller-owned Spotify client.
        playlist_id: Original destination.
        path: Original canonical history.
        today: Optional effective date.
        echo: Original skip presentation.
        progress: Original progress observer.
        retry: Original retry policy.
        cancel: Original cancellation callback.

    Returns:
        The configured application dependencies or workflow.
    """
    from spotify_manager.routines.blast_from_past import check_cancel

    effects = LegacyDormantRecovery(sp, playlist_id, path, retry, cancel)
    workflow = DormantRecovery(
        effects,
        partial(_clock, today),
        partial(check_cancel, cancel),
        partial(_progress, progress),
        echo,
        legacy.LOOKBACK_YEARS,
    )
    return workflow
