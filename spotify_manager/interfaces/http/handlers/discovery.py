"""Validate and present discovery HTTP requests."""

from fastapi import HTTPException
from spotipy import Spotify

from spotify_manager.interfaces.http import jobs
from spotify_manager.interfaces.http.models.discovery import NewKidsChoiceRequest
from spotify_manager.interfaces.http.models.jobs import BlastJobResult
from spotify_manager.interfaces.http.validation import option_ids
from spotify_manager.interfaces.operations import new_kids as new_kids


def cmd_flush_new_kids(client: Spotify, dry_run: bool) -> BlastJobResult:
    """Start an interactive New Kids flush with reconnectable web state.

    Args:
        client: Original validated client value.
        dry_run: Original validated dry run value.

    Returns:
        Original feature response with unchanged fields and validation.
    """
    playlist_ids = jobs._configured_album_discovery_playlists()
    return jobs.start_new_kids_job(client, *playlist_ids, dry_run=dry_run)


def cmd_active_new_kids_jobs() -> list[BlastJobResult]:
    """Return active New Kids jobs so the web UI can reconnect after reload.

    Returns:
        Original feature response with unchanged fields and validation.
    """
    return jobs._active_playlist_jobs("flush_new_kids")


def cmd_new_kids_job(job_id: str) -> BlastJobResult:
    """Return current progress and any pending New Kids choice.

    Args:
        job_id: Original validated job id value.

    Returns:
        Original feature response with unchanged fields and validation.
    """
    job = jobs.get_blast_job(job_id, command="flush_new_kids")
    with jobs._blast_jobs_lock:
        return jobs._blast_job_snapshot(job)


def cmd_choose_new_kids_release(
    job_id: str, request: NewKidsChoiceRequest
) -> BlastJobResult:
    """Submit one release or control choice to a waiting New Kids job.

    Args:
        job_id: Original validated job id value.
        request: Original validated request value.

    Returns:
        Original feature response with unchanged fields and validation.

    Raises:
        HTTPException: An original validation or feature error is observed.
    """
    job = jobs.get_blast_job(job_id, command="flush_new_kids")
    with jobs._blast_jobs_lock:
        pending = job.result.new_kids_pending_choice
        if job.result.status != "waiting" or pending is None:
            raise HTTPException(
                status_code=409,
                detail="New Kids job is not waiting for a release choice",
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


def cmd_cancel_new_kids_job(job_id: str) -> BlastJobResult:
    """Request a clean stop at the next New Kids processing boundary.

    Args:
        job_id: Original validated job id value.

    Returns:
        Original feature response with unchanged fields and validation.

    Raises:
        HTTPException: An original validation or feature error is observed.
    """
    job = jobs.get_blast_job(job_id, command="flush_new_kids")
    with jobs._blast_jobs_lock:
        if job.result.status not in jobs._ACTIVE_JOB_STATUSES:
            raise HTTPException(status_code=409, detail="New Kids job is not active")
        job.result.status = "cancelling"
        job.result.new_kids_pending_choice = None
        job.result.detail = "Stopping New Kids flush"
        jobs._append_blast_log_locked(job, job.result.detail)
        job.cancel_event.set()
        job.choice_event.set()
        return jobs._blast_job_snapshot(job)
