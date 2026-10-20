"""Invoke blast from past use cases for CLI and HTTP features."""

from datetime import date as date
from pathlib import Path as Path

from spotipy import Spotify as Spotify

from spotify_manager.application.historical_resolution import (
    direct_call as _direct_retry,
)
from spotify_manager.application.historical_values import (
    BlastFromPastBatch as BlastFromPastBatch,
)
from spotify_manager.application.historical_values import (
    BlastFromPastCancelledError as BlastFromPastCancelledError,
)
from spotify_manager.application.historical_values import (
    BlastFromPastConfigError as BlastFromPastConfigError,
)
from spotify_manager.application.historical_values import (
    BlastFromPastError as BlastFromPastError,
)
from spotify_manager.application.historical_values import (
    BlastFromPastSpotifySummary as BlastFromPastSpotifySummary,
)
from spotify_manager.application.historical_values import (
    LastFmExportError as LastFmExportError,
)
from spotify_manager.application.historical_values import PlaylistState as PlaylistState
from spotify_manager.application.historical_values import (
    SpotifySelectionResolution as SpotifySelectionResolution,
)
from spotify_manager.application.historical_values import (
    SpotifySelectionResult as SpotifySelectionResult,
)
from spotify_manager.application.historical_values import (
    SpotifyTrackMatch as SpotifyTrackMatch,
)
from spotify_manager.bootstrap.historical_playlists import blast_playlist
from spotify_manager.bootstrap.historical_playlists import blast_selection
from spotify_manager.bootstrap.historical_playlists import historical_resolution
from spotify_manager.domain.history import Scrobble as Scrobble
from spotify_manager.domain.history import ScrobbleSelection as ScrobbleSelection
from spotify_manager.routines.blast_from_past import (
    DEFAULT_SCROBBLES_PATH as DEFAULT_SCROBBLES_PATH,
)
from spotify_manager.routines.blast_from_past import (
    FIRST_ELIGIBLE_DATE as FIRST_ELIGIBLE_DATE,
)
from spotify_manager.routines.blast_from_past import (
    SCROBBLE_TIMEZONE as SCROBBLE_TIMEZONE,
)
from spotify_manager.routines.blast_from_past import CancelCheck as CancelCheck
from spotify_manager.routines.blast_from_past import (
    ProgressCallback as ProgressCallback,
)
from spotify_manager.routines.blast_from_past import (
    RandomIndexReader as RandomIndexReader,
)
from spotify_manager.routines.blast_from_past import RetryCall as RetryCall
from spotify_manager.routines.blast_from_past import check_cancel as check_cancel
from spotify_manager.routines.blast_from_past import (
    fetch_random_indexes as fetch_random_indexes,
)
from spotify_manager.routines.blast_from_past import (
    parse_playlist_id as parse_playlist_id,
)


def select_blast_from_past(
    count: int = 10,
    path: Path = DEFAULT_SCROBBLES_PATH,
    today: date | None = None,
    random_index_reader: RandomIndexReader = fetch_random_indexes,
    progress_callback: ProgressCallback | None = None,
) -> BlastFromPastBatch:
    """Select a Friday-routine batch from the Last.fm export.

    Args:
        count: Number of populated historical dates to select.
        path: Existing history export.
        today: Optional effective local date for the cutoff.
        random_index_reader: Existing source of unique indexes and one timestamp.
        progress_callback: Optional progress presenter.

    Returns:
        Selected plays in response-index order with the original cutoff.

    Raises:
        BlastFromPastError: Count or eligible-date population is invalid.
        LastFmExportError: History cannot be read.
        RandomOrgError: The random source fails.
    """
    configured = blast_selection(path, today, random_index_reader, progress_callback)
    return configured.run(count)


def resolve_spotify_selections(
    sp: Spotify,
    selections: tuple[ScrobbleSelection, ...],
    playlist: PlaylistState,
    progress_callback: ProgressCallback | None = None,
    retry_call: RetryCall = _direct_retry,
    cancel_check: CancelCheck | None = None,
) -> SpotifySelectionResolution:
    """Resolve selected scrobbles and identify new playlist tracks.

    Args:
        sp: Caller-owned Spotify client.
        selections: Original ordered selected plays.
        playlist: Observed destination membership.
        progress_callback: Optional progress presenter.
        retry_call: Original retry policy.
        cancel_check: Optional cancellation predicate.

    Returns:
        Ordered decisions and unique pending additions.

    Raises:
        SpotifyTrackResolutionError: Spotify observations are unusable.
        BlastFromPastCancelledError: Cancellation is requested.
    """
    configured = historical_resolution(sp, progress_callback, retry_call, cancel_check)
    return configured.run(selections, playlist)


def add_blast_from_past_to_spotify(
    sp: Spotify,
    playlist_id: str,
    count: int | None = 10,
    max_playlist_length: int | None = None,
    path: Path = DEFAULT_SCROBBLES_PATH,
    today: date | None = None,
    random_index_reader: RandomIndexReader = fetch_random_indexes,
    progress_callback: ProgressCallback | None = None,
    retry_call: RetryCall = _direct_retry,
    cancel_check: CancelCheck | None = None,
    dry_run: bool = False,
) -> BlastFromPastSpotifySummary:
    """Select, resolve, and append a blast-from-the-past batch to Spotify.

    Args:
        sp: Caller-owned Spotify client.
        playlist_id: Destination playlist.
        count: Optional explicit historical date count.
        max_playlist_length: Optional destination capacity, exclusive with count.
        path: Existing history export.
        today: Optional effective local date for the cutoff.
        random_index_reader: Existing random-index source.
        progress_callback: Optional progress presenter.
        retry_call: Original retry policy.
        cancel_check: Optional cancellation predicate.
        dry_run: Suppress writes while retaining resolved added actions.

    Returns:
        Original summary with observed and projected destination sizes.

    Raises:
        BlastFromPastError: Configuration, selection or observations fail.
        BlastFromPastCancelledError: Cancellation is requested.
    """
    configured = blast_playlist(
        sp,
        playlist_id,
        path,
        today,
        random_index_reader,
        progress_callback,
        retry_call,
        cancel_check,
    )
    return configured.run(playlist_id, count, max_playlist_length, dry_run)
