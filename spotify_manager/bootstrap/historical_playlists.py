"""Compose historical selections and playlist effects with legacy boundaries."""

from datetime import date
from functools import partial
from pathlib import Path

from spotipy import Spotify

from spotify_manager.application.historical_playlists import AnniversaryPlaylist
from spotify_manager.application.historical_playlists import BlastPlaylist
from spotify_manager.application.historical_playlists import HistoricalPlaylistEffects
from spotify_manager.application.historical_resolution import HistoricalResolution
from spotify_manager.application.historical_selection import AnniversarySelection
from spotify_manager.application.historical_selection import BlastSelection
from spotify_manager.application.historical_values import BlastFromPastBatch
from spotify_manager.infrastructure.legacy.historical_playlists import (
    LegacyHistoricalPlaylist,
)
from spotify_manager.routines import blast_from_past as blast
from spotify_manager.routines import daily_mind_radio as radio


def _progress(callback: blast.ProgressCallback | None, message: str) -> None:
    if callback is not None:
        callback(message)


def _today(today: date | None) -> date:
    return today or radio.datetime.now(blast.SCROBBLE_TIMEZONE).date()


def _effects(
    sp: Spotify,
    playlist_id: str,
    progress: blast.ProgressCallback | None,
    retry: blast.RetryCall,
    cancel: blast.CancelCheck | None,
) -> HistoricalPlaylistEffects:
    from spotify_manager.routines.blast_from_past import check_cancel

    adapter = LegacyHistoricalPlaylist(sp, playlist_id, progress, retry, cancel)
    return HistoricalPlaylistEffects(
        adapter.read,
        adapter.resolve,
        adapter.append,
        partial(check_cancel, cancel),
        partial(_progress, progress),
    )


def blast_selection(
    path: Path,
    today: date | None,
    random: blast.RandomIndexReader,
    progress: blast.ProgressCallback | None,
) -> BlastSelection:
    """Construct the invocation dependencies without executing the use case.

    Args:
        path: Local history export.
        today: Optional effective calendar date.
        random: Original random-index source.
        progress: Optional presenter.

    Returns:
        The configured application dependencies or workflow.
    """
    from spotify_manager.routines.blast_from_past import eligible_dates
    from spotify_manager.routines.blast_from_past import friday_track_cutoff
    from spotify_manager.routines.blast_from_past import load_scrobbles_by_date
    from spotify_manager.routines.blast_from_past import select_scrobble

    workflow = BlastSelection(
        partial(load_scrobbles_by_date, path),
        partial(friday_track_cutoff, today),
        eligible_dates,
        random,
        select_scrobble,
        partial(_progress, progress),
    )
    return workflow


def anniversary_selection(
    path: Path,
    today: date | None,
    random: radio.RandomTimestampReader,
    progress: blast.ProgressCallback | None,
) -> AnniversarySelection:
    """Construct the invocation dependencies without executing the use case.

    Args:
        path: Local history export.
        today: Optional effective local date.
        random: Shared timestamp source.
        progress: Optional presenter.

    Returns:
        The configured application dependencies or workflow.
    """
    from spotify_manager.routines.blast_from_past import load_scrobbles_by_date
    from spotify_manager.routines.blast_from_past import select_scrobble
    from spotify_manager.routines.daily_mind_radio import anniversary_dates

    workflow = AnniversarySelection(
        partial(load_scrobbles_by_date, path),
        partial(_today, today),
        anniversary_dates,
        random,
        select_scrobble,
        partial(_progress, progress),
    )
    return workflow


def _blast_batch(
    path: Path,
    today: date | None,
    random: blast.RandomIndexReader,
    progress: blast.ProgressCallback | None,
    count: int,
) -> BlastFromPastBatch:
    return blast_selection(path, today, random, progress).run(count)


def blast_playlist(
    sp: Spotify,
    playlist_id: str,
    path: Path,
    today: date | None,
    random: blast.RandomIndexReader,
    progress: blast.ProgressCallback | None,
    retry: blast.RetryCall,
    cancel: blast.CancelCheck | None,
) -> BlastPlaylist:
    """Construct the invocation dependencies without executing the use case.

    Args:
        sp: Caller-owned Spotify client.
        playlist_id: Destination playlist.
        path: Local history export.
        today: Optional effective local date.
        random: Original random-index reader.
        progress: Optional presenter.
        retry: Original retry policy.
        cancel: Optional cancellation predicate.

    Returns:
        The configured application dependencies or workflow.
    """
    select = partial(_blast_batch, path, today, random, progress)
    workflow = BlastPlaylist(_effects(sp, playlist_id, progress, retry, cancel), select)
    return workflow


def anniversary_playlist(
    sp: Spotify,
    playlist_id: str,
    path: Path,
    today: date | None,
    random: radio.RandomTimestampReader,
    progress: blast.ProgressCallback | None,
    retry: blast.RetryCall,
    cancel: blast.CancelCheck | None,
) -> AnniversaryPlaylist:
    """Construct the invocation dependencies without executing the use case.

    Args:
        sp: Caller-owned Spotify client.
        playlist_id: Destination playlist.
        path: Local history export.
        today: Optional effective local date.
        random: Original random timestamp reader.
        progress: Optional presenter.
        retry: Original retry policy.
        cancel: Optional cancellation predicate.

    Returns:
        The configured application dependencies or workflow.
    """
    select = partial(_anniversary_batch, path, today, random, progress)
    workflow = AnniversaryPlaylist(
        _effects(sp, playlist_id, progress, retry, cancel), select
    )
    return workflow


def historical_resolution(
    sp: Spotify,
    progress: blast.ProgressCallback | None,
    retry: blast.RetryCall,
    cancel: blast.CancelCheck | None,
) -> HistoricalResolution:
    """Construct the invocation dependencies without executing the use case.

    Args:
        sp: Caller-owned Spotify client.
        progress: Optional presenter.
        retry: Existing caller retry policy.
        cancel: Optional cancellation predicate.

    Returns:
        The configured application dependencies or workflow.
    """
    from spotify_manager.infrastructure.legacy.historical_playlists import (
        LegacyHistoricalMatches,
    )
    from spotify_manager.routines.blast_from_past import check_cancel

    adapter = LegacyHistoricalMatches(sp, retry, cancel)
    workflow = HistoricalResolution(
        adapter.search,
        adapter.liked,
        partial(check_cancel, cancel),
        partial(_progress, progress),
        blast.ALBUM_MATCH_THRESHOLD,
    )
    return workflow


def _anniversary_batch(
    path: Path,
    today: date | None,
    random: radio.RandomTimestampReader,
    progress: blast.ProgressCallback | None,
) -> radio.DailyMindRadioBatch:
    return anniversary_selection(path, today, random, progress).run()
