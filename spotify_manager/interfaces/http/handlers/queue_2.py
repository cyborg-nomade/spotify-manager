"""Validate and present queue 2 HTTP requests."""

from fastapi import HTTPException

from spotify_manager.application.ports.spotify_client import SpotifyClient as Spotify
from spotify_manager.interfaces.http import jobs
from spotify_manager.interfaces.http.models.discovery import NewKidsChoiceRequest
from spotify_manager.interfaces.http.models.jobs import BlastJobResult
from spotify_manager.interfaces.http.validation import option_ids
from spotify_manager.interfaces.operations import new_kids as new_kids


async def cmd_flush_queue_2(client: Spotify, dry_run: bool) -> BlastJobResult:
    """Start an interactive Queue 2 flush with reconnectable web state.

    Args:
        client: Original validated client value.
        dry_run: Original validated dry run value.

    Returns:
        Original feature response with unchanged fields and validation.
    """
    playlist_ids = jobs._configured_album_discovery_playlists()
    return await jobs.start_queue_2_job(client, *playlist_ids, dry_run=dry_run)


def cmd_active_queue_2_jobs() -> list[BlastJobResult]:
    """Return active Queue 2 jobs so the web UI can reconnect after reload.

    Returns:
        Original feature response with unchanged fields and validation.
    """
    return jobs._active_playlist_jobs("flush_queue_2")


def cmd_queue_2_job(job_id: str) -> BlastJobResult:
    """Return current progress and any pending Queue 2 choice.

    Args:
        job_id: Original validated job id value.

    Returns:
        Original feature response with unchanged fields and validation.
    """
    job = jobs.get_blast_job(job_id, command="flush_queue_2")
    with jobs._blast_jobs_lock:
        return jobs._blast_job_snapshot(job)


def cmd_choose_queue_2_release(
    job_id: str, request: NewKidsChoiceRequest
) -> BlastJobResult:
    """Submit one release or control choice to a waiting Queue 2 job.

    Args:
        job_id: Original validated job id value.
        request: Original validated request value.

    Returns:
        Original feature response with unchanged fields and validation.

    Raises:
        HTTPException: An original validation or feature error is observed.
    """
    job = jobs.get_blast_job(job_id, command="flush_queue_2")
    with jobs._blast_jobs_lock:
        pending = job.result.new_kids_pending_choice
        if job.result.status != "waiting" or pending is None:
            raise HTTPException(
                status_code=409,
                detail="Queue 2 job is not waiting for a release choice",
            )
        allowed = {
            new_kids.CHOICE_SKIP,
            new_kids.CHOICE_QUIT,
            *option_ids(pending.releases),
        }
        if request.choice not in allowed:
            raise HTTPException(
                status_code=400, detail="release choice is not available"
            )
        job.submitted_choice = request.choice
        job.result.new_kids_pending_choice = None
        job.result.status = "running"
        job.result.detail = "Release choice submitted"
        job.choice_event.set()
        return jobs._blast_job_snapshot(job)


def cmd_cancel_queue_2_job(job_id: str) -> BlastJobResult:
    """Request a clean stop at the next Queue 2 processing boundary.

    Args:
        job_id: Original validated job id value.

    Returns:
        Original feature response with unchanged fields and validation.

    Raises:
        HTTPException: An original validation or feature error is observed.
    """
    job = jobs.get_blast_job(job_id, command="flush_queue_2")
    with jobs._blast_jobs_lock:
        if job.result.status not in jobs._ACTIVE_JOB_STATUSES:
            raise HTTPException(status_code=409, detail="Queue 2 job is not active")
        job.result.status = "cancelling"
        job.result.new_kids_pending_choice = None
        job.result.detail = "Stopping Queue 2 flush"
        jobs._append_blast_log_locked(job, job.result.detail)
        job.cancel_event.set()
        job.choice_event.set()
        return jobs._blast_job_snapshot(job)
