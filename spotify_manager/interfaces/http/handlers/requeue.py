"""Validate and present requeue HTTP requests."""

from fastapi import HTTPException

from spotify_manager.application.ports.spotify_client import SpotifyClient as Spotify
from spotify_manager.interfaces.http import jobs
from spotify_manager.interfaces.http.models.jobs import BlastJobResult
from spotify_manager.interfaces.http.models.requeue import RequeueChoiceRequest
from spotify_manager.interfaces.operations import (
    requeue_for_a_dream as requeue_for_a_dream,
)


async def cmd_flush_requeue_for_a_dream(
    client: Spotify, dry_run: bool
) -> BlastJobResult:
    """Start a reconnectable Requeue for a Dream transition.

    Args:
        client: Original validated client value.
        dry_run: Original validated dry run value.

    Returns:
        Original feature response with unchanged fields and validation.

    Raises:
        HTTPException: An original validation or feature error is observed.
    """
    configuration = jobs.Settings()
    try:
        playlist_id = requeue_for_a_dream.parse_playlist_id(
            configuration.reqeueue_for_a_dream_playlist
        )
    except requeue_for_a_dream.RequeueForADreamConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return await jobs.start_requeue_for_a_dream_job(
        client, playlist_id, dry_run=dry_run
    )


def cmd_active_requeue_for_a_dream_jobs() -> list[BlastJobResult]:
    """Return active Requeue for a Dream jobs after a page reload.

    Returns:
        Original feature response with unchanged fields and validation.
    """
    return jobs._active_playlist_jobs("flush_requeue_for_a_dream")


def cmd_requeue_for_a_dream_job(job_id: str) -> BlastJobResult:
    """Return the current state and logs for one Requeue transition.

    Args:
        job_id: Original validated job id value.

    Returns:
        Original feature response with unchanged fields and validation.
    """
    job = jobs.get_blast_job(job_id, command="flush_requeue_for_a_dream")
    with jobs._blast_jobs_lock:
        return jobs._blast_job_snapshot(job)


def cmd_cancel_requeue_for_a_dream_job(job_id: str) -> BlastJobResult:
    """Request a clean stop at the next API or retry boundary.

    Args:
        job_id: Original validated job id value.

    Returns:
        Original feature response with unchanged fields and validation.

    Raises:
        HTTPException: An original validation or feature error is observed.
    """
    job = jobs.get_blast_job(job_id, command="flush_requeue_for_a_dream")
    with jobs._blast_jobs_lock:
        if job.result.status not in jobs._ACTIVE_JOB_STATUSES:
            raise HTTPException(
                status_code=409, detail="Requeue for a Dream job is not active"
            )
        job.result.status = "cancelling"
        job.result.requeue_pending_choice = None
        job.result.detail = "Stopping Requeue for a Dream"
        jobs._append_blast_log_locked(job, job.result.detail)
        job.cancel_event.set()
        job.choice_event.set()
        return jobs._blast_job_snapshot(job)


def cmd_choose_requeue_album(
    job_id: str, request: RequeueChoiceRequest
) -> BlastJobResult:
    """Submit one decision for the current proposed successor under the job lock.

    Args:
        job_id: Owning Requeue job identity.
        request: Explicit decision and the displayed request identity.

    Returns:
        Detached job state after accepting the submission.

    Raises:
        HTTPException: The job, pending request or submitted identity is not current.
    """
    job = jobs.get_blast_job(job_id, command="flush_requeue_for_a_dream")
    with jobs._blast_jobs_lock:
        pending = job.result.requeue_pending_choice
        if job.result.status != "waiting" or pending is None:
            raise HTTPException(
                status_code=409, detail="Requeue is not waiting for an album choice"
            )
        if request.request_id != pending.request_id:
            raise HTTPException(
                status_code=409, detail="Requeue album choice is no longer current"
            )
        job.submitted_choice = request.choice
        job.result.requeue_pending_choice = None
        job.result.status = "running"
        job.result.detail = "Requeue album choice submitted"
        job.choice_event.set()
        return jobs._blast_job_snapshot(job)
