"""Stable discovery result serialization."""

from collections.abc import Iterable

from spotify_manager.interfaces.http.job_records import PlaylistJob as _BlastJob
from spotify_manager.interfaces.http.models.discovery import NewKidsFillResult
from spotify_manager.interfaces.http.models.discovery import NewKidsTrackResult
from spotify_manager.interfaces.http.models.discovery import Queue3AnnualImportEntry
from spotify_manager.interfaces.http.models.discovery import Queue3ReleaseOption
from spotify_manager.interfaces.http.models.discovery import Queue3TrackResult
from spotify_manager.interfaces.operations import new_kids as new_kids
from spotify_manager.interfaces.operations import queue_3 as queue_3
from spotify_manager.interfaces.operations import slow_listening as slow_listening


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


def _apply_queue_3_annual_summary(
    job: _BlastJob, summary: queue_3.AnnualImportSummary
) -> None:
    """Apply a completed annual-only summary to its web job."""
    job.result.status = "completed"
    job.result.processed = len(summary.results)
    job.result.total = len(summary.results)
    job.result.added = summary.additions
    job.result.queue_3_annual_import = queue_3_annual_entries(summary.results)
    job.result.queue_3_annual_import_completed = summary.already_completed
    if summary.already_completed:
        job.result.detail = (
            f"Great Discoveries {summary.source_year} was already imported."
        )
    else:
        action = "would be added" if summary.dry_run else "added"
        artist_label = "artist" if summary.additions == 1 else "artists"
        job.result.detail = (
            f"Great Discoveries {summary.source_year}: {summary.additions} "
            f"{artist_label} {action}; {summary.already_present} already present."
        )


def _apply_queue_3_flush_summary(job: _BlastJob, summary: queue_3.FlushSummary) -> None:
    """Apply a completed or paused flush summary to its web job."""
    job.result.status = "paused" if summary.paused else "completed"
    job.result.run_id = summary.run_id
    job.result.processed = summary.processed
    job.result.total = summary.total
    job.result.advanced = summary.advanced
    job.result.queue_3_changed_releases = summary.changed_releases
    job.result.completed_artists = summary.completed_artists
    job.result.skipped = summary.skipped
    job.result.queue_3_results = queue_3_track_results(summary.results)
    job.result.queue_3_annual_import = queue_3_annual_entries(summary.annual_import)
    job.result.queue_3_resumed = summary.resumed
    job.result.queue_3_paused = summary.paused
    if summary.paused:
        job.result.detail = "Queue 3 flush paused. Progress was saved."
    else:
        job.result.detail = (
            f"{summary.processed} decisions; {summary.advanced} advances; "
            f"{summary.changed_releases} release changes; "
            f"{summary.completed_artists} completed artists."
        )


def queue_3_track_results(
    values: Iterable[queue_3.FlushResult],
) -> list[Queue3TrackResult]:
    """Present the complete collection in encounter order.

    Args:
        values: Complete routine values in encounter order.

    Returns:
        Complete response entries, preserving the first conversion failure.
    """
    entries = []
    for value in values:
        entries.append(queue_3_track_result(value))
    return entries


def new_kids_fill_results(
    values: Iterable[new_kids.FillResult],
) -> list[NewKidsFillResult]:
    """Present the complete collection in encounter order.

    Args:
        values: Complete routine values in encounter order.

    Returns:
        Complete response entries, preserving the first conversion failure.
    """
    entries = []
    for value in values:
        entries.append(new_kids_fill_result(value))
    return entries
