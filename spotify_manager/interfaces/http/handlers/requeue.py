"""Validate and present requeue HTTP requests."""

from fastapi import HTTPException

from spotify_manager.application.ports.spotify_client import SpotifyClient as Spotify
from spotify_manager.interfaces.http import jobs
from spotify_manager.interfaces.http.models.jobs import BlastJobResult
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
        job.result.detail = "Stopping Requeue for a Dream"
        jobs._append_blast_log_locked(job, job.result.detail)
        job.cancel_event.set()
        return jobs._blast_job_snapshot(job)
