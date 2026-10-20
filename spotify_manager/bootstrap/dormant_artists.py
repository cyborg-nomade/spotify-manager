"""Compose dormant history and catalog policies with original clocks and effects."""

from datetime import date
from functools import partial
from pathlib import Path

from spotipy import Spotify

from spotify_manager.application.dormant_recovery import DormantRecovery
from spotify_manager.application.dormant_tracks import DormantLikedTrack
from spotify_manager.infrastructure.legacy.dormant_artists import LegacyDormantRecovery
from spotify_manager.infrastructure.legacy.dormant_tracks import LegacyDormantCatalog
from spotify_manager.routines import blast_from_past_artists as legacy


def _clock(today: date | None) -> date:
    return today or legacy.datetime.now(legacy.blast_from_past.SCROBBLE_TIMEZONE).date()


def _progress(
    callback: legacy.ProgressCallback | None, done: int, count: int, message: str
) -> None:
    if callback is not None:
        callback(done, count, message)


def dormant_tracks(sp: Spotify, retry: legacy.RetryCall) -> DormantLikedTrack:
    """Construct original dormant-track resources without executing selection.

    Args:
        sp: Caller-owned synchronous Spotify client.
        retry: Original retry and cancellation boundary.

    Returns:
        Named liked-track application stage.
    """
    return DormantLikedTrack(LegacyDormantCatalog(sp, retry))


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
        dormant_tracks(sp, retry),
        partial(_clock, today),
        partial(check_cancel, cancel),
        partial(_progress, progress),
        echo,
        legacy.LOOKBACK_YEARS,
    )
    return workflow
