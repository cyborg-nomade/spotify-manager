"""Stable something old result serialization."""

from datetime import datetime

from spotify_manager.domain.something_old_history import PreviousMode
from spotify_manager.interfaces.http.models.something_old import (
    SomethingOldPreviousMode,
)
from spotify_manager.interfaces.http.models.something_old import SomethingOldTrackResult
from spotify_manager.interfaces.operations import something_old as something_old
from spotify_manager.interfaces.presenters.something_old_history import (
    mode_history_label,
)
from spotify_manager.routines import blast_from_past


def previous_mode_results(
    previous: tuple[PreviousMode, ...],
) -> list[SomethingOldPreviousMode]:
    """Present recorded use of the three mode options.

    Args:
        previous: Completed usage for the accepted Spotify artist.

    Returns:
        Additive wire metadata and shared readable labels.
    """
    result = []
    for entry in previous:
        result.append(
            SomethingOldPreviousMode(
                mode=entry.mode,
                count=entry.count,
                label=mode_history_label(entry),
                last_chosen_at=entry.last_chosen_at.isoformat()
                if entry.last_chosen_at
                else None,
                release_name=entry.release_name,
                provenance=entry.provenance,
            )
        )
    return result


def something_old_track_result(
    track: something_old.SelectedTrack,
) -> SomethingOldTrackResult:
    """Convert one Something Old selection into its API representation.

    Args:
        track: Accepted routine observation to present.

    Returns:
        The original wire fields, defaults and encounter order.
    """
    return SomethingOldTrackResult(
        spotify_id=track.spotify_id,
        track=track.track,
        album=track.album,
        artists=list(track.artists),
        source=track.source,
        lastfm_scrobbles=track.lastfm_scrobbles,
    )


def scrobble_date(timestamp_ms: int) -> str:
    """Format a scrobble timestamp in the existing listening timezone.

    Args:
        timestamp_ms: Original timestamp in milliseconds.

    Returns:
        The ISO calendar date used in the HTTP result.
    """
    return (
        datetime.fromtimestamp(timestamp_ms / 1000, blast_from_past.SCROBBLE_TIMEZONE)
        .date()
        .isoformat()
    )
