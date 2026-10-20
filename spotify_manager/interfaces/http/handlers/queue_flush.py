"""Validate and present queue flush HTTP requests."""

from spotipy import Spotify

from spotify_manager.interfaces.http import jobs
from spotify_manager.interfaces.http.models.jobs import BlastJobResult
from spotify_manager.interfaces.operations import the_queue as the_queue


def cmd_flush_queue(client: Spotify, dry_run: bool) -> BlastJobResult:
    """Start a reconnectable flush of the first ten Queue artists.

    Args:
        client: Original validated client value.
        dry_run: Original validated dry run value.

    Returns:
        Original feature response with unchanged fields and validation.
    """
    return jobs.start_queue_flush_job(
        client, jobs._configured_queue_playlists(), dry_run=dry_run
    )


def cmd_active_queue_flush_jobs() -> list[BlastJobResult]:
    """Return active Queue flush jobs for page reload reconnection.

    Returns:
        Original feature response with unchanged fields and validation.
    """
    return jobs._active_playlist_jobs("flush_queue")


def cmd_queue_flush_job(job_id: str) -> BlastJobResult:
    """Return current Queue flush progress and result details.

    Args:
        job_id: Original validated job id value.

    Returns:
        Original feature response with unchanged fields and validation.
    """
    job = jobs.get_blast_job(job_id, command="flush_queue")
    with jobs._blast_jobs_lock:
        return jobs._blast_job_snapshot(job)


def cmd_cancel_queue_flush_job(job_id: str) -> BlastJobResult:
    """Stop a Queue flush while preserving its durable checkpoint.

    Args:
        job_id: Original validated job id value.

    Returns:
        Original feature response with unchanged fields and validation.
    """
    return jobs._cancel_queue_job(job_id, "flush_queue", "Queue flush")
