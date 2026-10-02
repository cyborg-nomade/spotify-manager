"""Stable discovery result serialization."""

from spotify_manager.interfaces.http.models.discovery import NewKidsFillResult
from spotify_manager.interfaces.http.models.discovery import NewKidsTrackResult
from spotify_manager.interfaces.http.models.discovery import Queue3AnnualImportEntry
from spotify_manager.interfaces.http.models.discovery import Queue3ReleaseOption
from spotify_manager.interfaces.http.models.discovery import Queue3TrackResult
from spotify_manager.routines import new_kids
from spotify_manager.routines import queue_3
from spotify_manager.routines import slow_listening


def new_kids_track_result(result: new_kids.FlushResult) -> NewKidsTrackResult:
    """Convert one New Kids result into its stable API representation.

    Args:
        result: Accepted routine observation to present.

    Returns:
        The original wire fields, defaults and encounter order.
    """
    return NewKidsTrackResult(
        artist=result.artist,
        source_track=result.source_track,
        source_release=result.source_release,
        current_liked=result.current_liked,
        consecutive_unliked=result.consecutive_unliked,
        action=result.action,
        target_track=result.target_track,
        target_release=result.target_release,
        release_number=result.release_number,
        album_decision=result.album_decision,
        album_liked_tracks=result.album_liked_tracks,
        album_total_tracks=result.album_total_tracks,
        qualification_reasons=list(result.qualification_reasons),
        composer_playlist=result.composer_playlist,
        composer_position=result.composer_position,
        composer_limit=result.composer_limit,
    )


def new_kids_fill_result(result: new_kids.FillResult) -> NewKidsFillResult:
    """Convert one Queue 2 transfer into its web representation.

    Args:
        result: Accepted routine observation to present.

    Returns:
        The original wire fields, defaults and encounter order.
    """
    return NewKidsFillResult(
        artist=result.artist,
        track=result.track,
        action=result.action,
    )


def queue_3_release_option(
    release: slow_listening.DiscographyRelease,
) -> Queue3ReleaseOption:
    """Convert one Queue 3 boundary release for the web client.

    Args:
        release: Accepted routine observation to present.

    Returns:
        The original wire fields, defaults and encounter order.
    """
    return Queue3ReleaseOption(
        spotify_id=release.spotify_id,
        name=release.name,
        release_type=release.release_type,
        release_date=release.chronology_date,
        total_tracks=release.total_tracks,
    )


def queue_3_track_result(result: queue_3.FlushResult) -> Queue3TrackResult:
    """Convert one Queue 3 transition into its web representation.

    Args:
        result: Accepted routine observation to present.

    Returns:
        The original wire fields, defaults and encounter order.
    """
    return Queue3TrackResult(
        artist=result.artist,
        source_track=result.source_track,
        source_release=result.source_release,
        action=result.action,
        target_track=result.target_track,
        target_release=result.target_release,
        album_decision=result.album_decision,
        album_liked_tracks=result.album_liked_tracks,
        album_total_tracks=result.album_total_tracks,
        composer_playlist=result.composer_playlist,
        reason=result.reason,
    )


def queue_3_annual_entries(
    results: tuple[queue_3.AnnualImportResult, ...],
) -> list[Queue3AnnualImportEntry]:
    """Convert annual-import results into the stable web representation.

    Args:
        results: Accepted routine observation to present.

    Returns:
        The original wire fields, defaults and encounter order.
    """
    entries = []
    for result in results:
        entry = Queue3AnnualImportEntry(
            artist=result.artist,
            track=result.track,
            source_year=result.source_year,
            action=result.action,
        )
        entries.append(entry)
    return entries
