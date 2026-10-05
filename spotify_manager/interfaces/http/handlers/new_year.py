"""Validate and present new year HTTP requests."""

from spotipy import Spotify

from spotify_manager.interfaces.http import jobs
from spotify_manager.interfaces.http.job_records import PlaylistJob as _BlastJob
from spotify_manager.interfaces.http.job_registry import register_job
from spotify_manager.interfaces.http.models.jobs import BlastJobResult


def cmd_new_year(client: Spotify, dry_run: bool, year: int | None) -> BlastJobResult:
    """Start all New Year's Routines for the previous completed calendar year.

    Args:
        client: Original validated client value.
        dry_run: Original validated dry run value.
        year: Original validated year value.

    Returns:
        Original feature response with unchanged fields and validation.
    """
    with jobs._blast_jobs_lock:
        jobs._require_playlist_slot("another playlist or history routine is running")
        job_id = jobs.uuid4().hex
        job = _BlastJob(
            result=BlastJobResult(job_id=job_id, command="new_year", dry_run=dry_run)
        )
        snapshot = register_job(jobs._blast_jobs, job_id, job, jobs._blast_job_snapshot)
    jobs.Thread(
        target=jobs._run_new_year_job,
        args=(job_id, client, year, dry_run),
        name=f"new-year-{job_id[:8]}",
        daemon=True,
    ).start()
    return snapshot


def cmd_active_new_year_jobs() -> list[BlastJobResult]:
    """Reconnect to an active annual workflow after browser reload.

    Returns:
        Original feature response with unchanged fields and validation.
    """
    return jobs._active_playlist_jobs("new_year")


def cmd_new_year_job(job_id: str) -> BlastJobResult:
    """Return annual progress, rankings, and logs.

    Args:
        job_id: Original validated job id value.

    Returns:
        Original feature response with unchanged fields and validation.
    """
    job = jobs.get_blast_job(job_id, command="new_year")
    with jobs._blast_jobs_lock:
        return jobs._blast_job_snapshot(job)


def cmd_cancel_new_year_job(job_id: str) -> BlastJobResult:
    """Cancel at the next boundary, retaining completed annual steps.

    Args:
        job_id: Original validated job id value.

    Returns:
        Original feature response with unchanged fields and validation.
    """
    return jobs._cancel_simple_playlist_job(
        job_id, command="new_year", detail="Stopping New Year's Routines"
    )
