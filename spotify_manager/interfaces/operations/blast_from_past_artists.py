"""Invoke blast from past artists use cases for CLI and HTTP features."""

from datetime import date as date
from pathlib import Path as Path

from spotipy import Spotify as Spotify

from spotify_manager.application.dormant_values import (
    BlastFromPastArtistsError as BlastFromPastArtistsError,
)
from spotify_manager.application.dormant_values import (
    DormantArtistSummary as DormantArtistSummary,
)
from spotify_manager.application.historical_resolution import direct_call as direct_call
from spotify_manager.bootstrap.dormant_artists import dormant_recovery
from spotify_manager.bootstrap.dormant_artists import dormant_tracks
from spotify_manager.domain.dormant_artists import (
    DormantArtistResult as DormantArtistResult,
)
from spotify_manager.routines import new_kids as new_kids
from spotify_manager.routines.blast_from_past_artists import (
    DEFAULT_COUNT as DEFAULT_COUNT,
)
from spotify_manager.routines.blast_from_past_artists import (
    DEFAULT_SCROBBLES_PATH as DEFAULT_SCROBBLES_PATH,
)
from spotify_manager.routines.blast_from_past_artists import CancelCheck as CancelCheck
from spotify_manager.routines.blast_from_past_artists import Echo as Echo
from spotify_manager.routines.blast_from_past_artists import (
    ProgressCallback as ProgressCallback,
)
from spotify_manager.routines.blast_from_past_artists import RetryCall as RetryCall


def most_popular_liked_track(
    sp: Spotify, artist_id: str, retry_call: RetryCall
) -> new_kids.CatalogTrack | None:
    """Return the original preferred live-liked primary-credit marker.

    Args:
        sp: Caller-owned Spotify client.
        artist_id: Original mapped artist.
        retry_call: Original retry policy.

    Returns:
        Original preferred marker or no liked primary-credit track.

    Raises:
        BlastFromPastArtistsError: Original liked/detail response is invalid.
    """
    configured = dormant_tracks(sp, artist_id, retry_call)
    return configured.run()


def add_dormant_artists_to_blast_from_past(
    sp: Spotify,
    playlist_id: str,
    *,
    count: int = DEFAULT_COUNT,
    path: Path = DEFAULT_SCROBBLES_PATH,
    today: date | None = None,
    echo: Echo = print,
    progress_callback: ProgressCallback | None = None,
    retry_call: RetryCall = direct_call,
    cancel_check: CancelCheck | None = None,
    dry_run: bool = False,
) -> DormantArtistSummary:
    """Recover the requested original alphabetical dormant artists.

    Args:
        sp: Caller-owned Spotify client.
        playlist_id: Original destination.
        count: Requested marker count.
        path: Original canonical history location.
        today: Optional effective local calendar date.
        echo: Original skipped-candidate presentation.
        progress_callback: Original candidate and completion presentation.
        retry_call: Original retry policy.
        cancel_check: Original cancellation callback.
        dry_run: Original preview mode, retaining added result labels.

    Returns:
        Original completed recovery summary.

    Raises:
        ValueError: Count is below the original minimum.
        BlastFromPastArtistsError: Original catalog observations are unusable.
        BlastFromPastCancelledError: Original safe cancellation is requested.
    """
    configured = dormant_recovery(
        sp, playlist_id, path, today, echo, progress_callback, retry_call, cancel_check
    )
    return configured.run(count, dry_run)
