"""Invoke daily mind radio use cases for CLI and HTTP features."""

from datetime import date as date
from pathlib import Path as Path

from spotipy import Spotify as Spotify

from spotify_manager.application.historical_resolution import direct_call as direct_call
from spotify_manager.application.historical_values import (
    DailyMindRadioBatch as DailyMindRadioBatch,
)
from spotify_manager.application.historical_values import (
    DailyMindRadioSpotifySummary as DailyMindRadioSpotifySummary,
)
from spotify_manager.bootstrap.historical_playlists import anniversary_playlist
from spotify_manager.bootstrap.historical_playlists import anniversary_selection
from spotify_manager.routines import blast_from_past as blast_from_past
from spotify_manager.routines.blast_from_past import (
    fetch_random_timestamp as fetch_random_timestamp,
)
from spotify_manager.routines.daily_mind_radio import (
    RandomTimestampReader as RandomTimestampReader,
)


def select_daily_mind_radio(
    path: Path = blast_from_past.DEFAULT_SCROBBLES_PATH,
    today: date | None = None,
    random_timestamp_reader: RandomTimestampReader = (fetch_random_timestamp),
    progress_callback: blast_from_past.ProgressCallback | None = None,
) -> DailyMindRadioBatch:
    """Select one scrobble from each populated anniversary date.

    Args:
        path: Existing Last.fm history export.
        today: Optional effective local calendar date.
        random_timestamp_reader: Read one timestamp for all populated targets.
        progress_callback: Optional existing progress presenter.

    Returns:
        All targets, missing targets and selected plays with original date indexes.

    Raises:
        LastFmExportError: History has no date buckets or cannot be read.
        RandomOrgError: The random source fails.
    """
    configured = anniversary_selection(
        path, today, random_timestamp_reader, progress_callback
    )
    return configured.run()


def add_daily_mind_radio_to_spotify(
    sp: Spotify,
    playlist_id: str,
    path: Path = blast_from_past.DEFAULT_SCROBBLES_PATH,
    today: date | None = None,
    random_timestamp_reader: RandomTimestampReader = (fetch_random_timestamp),
    progress_callback: blast_from_past.ProgressCallback | None = None,
    retry_call: blast_from_past.RetryCall = direct_call,
    cancel_check: blast_from_past.CancelCheck | None = None,
    dry_run: bool = False,
) -> DailyMindRadioSpotifySummary:
    """Select anniversary scrobbles and append their Spotify matches.

    Args:
        sp: Caller-owned Spotify client.
        playlist_id: Destination playlist.
        path: Existing Last.fm history export.
        today: Optional effective local calendar date.
        random_timestamp_reader: Existing shared timestamp source.
        progress_callback: Optional progress presenter.
        retry_call: Original retry policy.
        cancel_check: Optional cancellation predicate.
        dry_run: Suppress remote writes while retaining resolution decisions.

    Returns:
        Original summary, with absent playlist lengths for empty selections.

    Raises:
        BlastFromPastError: Selection or Spotify observations fail.
        BlastFromPastCancelledError: Cancellation is requested.
    """
    configured = anniversary_playlist(
        sp,
        playlist_id,
        path,
        today,
        random_timestamp_reader,
        progress_callback,
        retry_call,
        cancel_check,
    )
    return configured.run(playlist_id, dry_run)
