"""Build the daily mind radio playlist from anniversary scrobbles."""

from collections.abc import Callable
from datetime import date
from datetime import datetime
from pathlib import Path

from spotipy import Spotify

from spotify_manager.application.historical_resolution import direct_call
from spotify_manager.application.historical_values import (
    DailyMindRadioBatch as DailyMindRadioBatch,
)
from spotify_manager.application.historical_values import (
    DailyMindRadioSpotifySummary as DailyMindRadioSpotifySummary,
)
from spotify_manager.domain import history as history_policy
from spotify_manager.routines import blast_from_past


ANNIVERSARY_INTERVAL_YEARS = 5
RandomTimestampReader = Callable[[], datetime]


def anniversary_dates(today: date, earliest_year: int) -> tuple[date, ...]:
    """Return last year's date followed by five-year steps into the past.

    Args:
        today: Effective local calendar date.
        earliest_year: Inclusive earliest year in the export.

    Returns:
        Newest-first anniversary dates, skipping invalid February 29 dates.
    """
    return history_policy.anniversary_dates(
        today, earliest_year, ANNIVERSARY_INTERVAL_YEARS
    )


def select_daily_mind_radio(
    path: Path = blast_from_past.DEFAULT_SCROBBLES_PATH,
    today: date | None = None,
    random_timestamp_reader: RandomTimestampReader = (
        blast_from_past.fetch_random_timestamp
    ),
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
    from spotify_manager.interfaces.operations.daily_mind_radio import (
        select_daily_mind_radio as operation,
    )

    return operation(path, today, random_timestamp_reader, progress_callback)


def add_daily_mind_radio_to_spotify(
    sp: Spotify,
    playlist_id: str,
    path: Path = blast_from_past.DEFAULT_SCROBBLES_PATH,
    today: date | None = None,
    random_timestamp_reader: RandomTimestampReader = (
        blast_from_past.fetch_random_timestamp
    ),
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
    from spotify_manager.interfaces.operations.daily_mind_radio import (
        add_daily_mind_radio_to_spotify as operation,
    )

    return operation(
        sp,
        playlist_id,
        path,
        today,
        random_timestamp_reader,
        progress_callback,
        retry_call,
        cancel_check,
        dry_run,
    )
