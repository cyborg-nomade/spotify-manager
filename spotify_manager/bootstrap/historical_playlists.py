"""Compose historical selections and playlist effects with legacy boundaries."""

from datetime import date
from functools import partial
from pathlib import Path

from spotipy import Spotify

from spotify_manager.application.historical_playlists import AnniversaryPlaylist
from spotify_manager.application.historical_playlists import BlastPlaylist
from spotify_manager.application.historical_playlists import HistoricalPlaylistEffects
from spotify_manager.application.historical_selection import AnniversarySelection
from spotify_manager.application.historical_selection import BlastSelection
from spotify_manager.application.historical_values import BlastFromPastBatch
from spotify_manager.application.historical_values import BlastFromPastSpotifySummary
from spotify_manager.application.historical_values import DailyMindRadioBatch
from spotify_manager.application.historical_values import DailyMindRadioSpotifySummary
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
    adapter = LegacyHistoricalPlaylist(sp, playlist_id, progress, retry, cancel)
    return HistoricalPlaylistEffects(
        adapter.read,
        adapter.resolve,
        adapter.append,
        partial(blast.check_cancel, cancel),
        partial(_progress, progress),
    )


def select_blast(
    count: int,
    path: Path,
    today: date | None,
    random: blast.RandomIndexReader,
    progress: blast.ProgressCallback | None,
) -> BlastFromPastBatch:
    """Bind Friday selection to its original public observation helpers.

    Args:
        count: Requested date count.
        path: Local history export.
        today: Optional effective calendar date.
        random: Original random-index source.
        progress: Optional presenter.

    Returns:
        Selected Friday batch.

    Raises:
        BlastFromPastError: Selection population or count is invalid.
    """
    workflow = BlastSelection(
        partial(blast.load_scrobbles_by_date, path),
        partial(blast.friday_track_cutoff, today),
        blast.eligible_dates,
        random,
        blast.select_scrobble,
        partial(_progress, progress),
    )
    return workflow.run(count)


def select_radio(
    path: Path,
    today: date | None,
    random: radio.RandomTimestampReader,
    progress: blast.ProgressCallback | None,
) -> DailyMindRadioBatch:
    """Bind anniversary selection to the original calendar and history boundaries.

    Args:
        path: Local history export.
        today: Optional effective local date.
        random: Shared timestamp source.
        progress: Optional presenter.

    Returns:
        Populated and missing anniversary dates with their selected tracks.

    Raises:
        LastFmExportError: History has no date buckets.
    """
    workflow = AnniversarySelection(
        partial(blast.load_scrobbles_by_date, path),
        partial(_today, today),
        radio.anniversary_dates,
        random,
        blast.select_scrobble,
        partial(_progress, progress),
    )
    return workflow.run()


def _blast_batch(
    path: Path,
    today: date | None,
    random: blast.RandomIndexReader,
    progress: blast.ProgressCallback | None,
    count: int,
) -> BlastFromPastBatch:
    return blast.select_blast_from_past(
        count=count,
        path=path,
        today=today,
        random_index_reader=random,
        progress_callback=progress,
    )


def add_blast(
    sp: Spotify,
    playlist_id: str,
    count: int | None,
    maximum: int | None,
    path: Path,
    today: date | None,
    random: blast.RandomIndexReader,
    progress: blast.ProgressCallback | None,
    retry: blast.RetryCall,
    cancel: blast.CancelCheck | None,
    dry_run: bool,
) -> BlastFromPastSpotifySummary:
    """Compose the Friday playlist workflow without moving API reads across choices.

    Args:
        sp: Caller-owned Spotify client.
        playlist_id: Destination playlist.
        count: Optional explicit date count.
        maximum: Optional destination capacity.
        path: Local history export.
        today: Optional effective local date.
        random: Original random-index reader.
        progress: Optional presenter.
        retry: Original retry policy.
        cancel: Optional cancellation predicate.
        dry_run: Suppress remote mutation.

    Returns:
        Original public playlist summary.

    Raises:
        BlastFromPastError: Selection, configuration or observations fail.
    """
    select = partial(_blast_batch, path, today, random, progress)
    workflow = BlastPlaylist(_effects(sp, playlist_id, progress, retry, cancel), select)
    return workflow.run(playlist_id, count, maximum, dry_run)


def add_radio(
    sp: Spotify,
    playlist_id: str,
    path: Path,
    today: date | None,
    random: radio.RandomTimestampReader,
    progress: blast.ProgressCallback | None,
    retry: blast.RetryCall,
    cancel: blast.CancelCheck | None,
    dry_run: bool,
) -> DailyMindRadioSpotifySummary:
    """Compose anniversary selection before any destination playlist observation.

    Args:
        sp: Caller-owned Spotify client.
        playlist_id: Destination playlist.
        path: Local history export.
        today: Optional effective local date.
        random: Original random timestamp reader.
        progress: Optional presenter.
        retry: Original retry policy.
        cancel: Optional cancellation predicate.
        dry_run: Suppress remote mutation.

    Returns:
        Original summary, including nullable lengths for empty selections.

    Raises:
        BlastFromPastError: Selection or observations fail.
    """
    select = partial(
        radio.select_daily_mind_radio,
        path=path,
        today=today,
        random_timestamp_reader=random,
        progress_callback=progress,
    )
    workflow = AnniversaryPlaylist(
        _effects(sp, playlist_id, progress, retry, cancel), select
    )
    return workflow.run(playlist_id, dry_run)


def resolve_matches(
    sp: Spotify,
    selections: tuple[blast.ScrobbleSelection, ...],
    playlist: blast.PlaylistState,
    progress: blast.ProgressCallback | None,
    retry: blast.RetryCall,
    cancel: blast.CancelCheck | None,
) -> blast.SpotifySelectionResolution:
    """Compose historical match resolution with the existing Spotify observations.

    Args:
        sp: Caller-owned Spotify client.
        selections: Ordered historical plays.
        playlist: Observed destination membership.
        progress: Optional presenter.
        retry: Existing caller retry policy.
        cancel: Optional cancellation predicate.

    Returns:
        Original match outcomes and pending additions.

    Raises:
        BlastFromPastError: Observation or cancellation fails.
    """
    from spotify_manager.application.historical_resolution import HistoricalResolution
    from spotify_manager.infrastructure.legacy.historical_playlists import (
        LegacyHistoricalMatches,
    )

    adapter = LegacyHistoricalMatches(sp, retry, cancel)
    workflow = HistoricalResolution(
        adapter.search,
        adapter.liked,
        partial(blast.check_cancel, cancel),
        partial(_progress, progress),
        blast.ALBUM_MATCH_THRESHOLD,
    )
    return workflow.run(selections, playlist)
