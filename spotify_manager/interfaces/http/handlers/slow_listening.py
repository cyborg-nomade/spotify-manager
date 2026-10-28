"""Validate and present slow listening HTTP requests."""

from fastapi import HTTPException

from spotify_manager.application.ports.spotify_client import SpotifyClient as Spotify
from spotify_manager.interfaces.http import jobs
from spotify_manager.interfaces.http.models.jobs import BlastJobResult
from spotify_manager.interfaces.http.models.slow_listening import (
    SlowListeningChoiceRequest,
)
from spotify_manager.interfaces.http.models.slow_listening import (
    SlowListeningPendingChoice,
)
from spotify_manager.interfaces.http.validation import option_ids
from spotify_manager.interfaces.operations import slow_listening as slow_listening


async def cmd_flush_slow_listening(client: Spotify, dry_run: bool) -> BlastJobResult:
    """Start an interactive Slow Listening flush with reconnectable state.

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
        playlist_id = slow_listening.parse_playlist_id(
            configuration.slow_listening_playlist
        )
    except slow_listening.SlowListeningConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return await jobs.start_slow_listening_job(client, playlist_id, dry_run=dry_run)


def cmd_active_slow_listening_jobs() -> list[BlastJobResult]:
    """Return active Slow Listening jobs for page-reload reconnection.

    Returns:
        Original feature response with unchanged fields and validation.
    """
    return jobs._active_playlist_jobs("flush_slow_listening")


def cmd_slow_listening_job(job_id: str) -> BlastJobResult:
    """Return current progress and the pending Slow Listening choice.

    Args:
        job_id: Original validated job id value.

    Returns:
        Original feature response with unchanged fields and validation.
    """
    job = jobs.get_blast_job(job_id, command="flush_slow_listening")
    with jobs._blast_jobs_lock:
        return jobs._blast_job_snapshot(job)


def cmd_choose_slow_listening_track(
    job_id: str, request: SlowListeningChoiceRequest
) -> BlastJobResult:
    """Submit a candidate, release order, or completion acknowledgement.

    Args:
        job_id: Original validated job id value.
        request: Original validated request value.

    Returns:
        Original feature response with unchanged fields and validation.

    Raises:
        HTTPException: An original validation or feature error is observed.
    """
    job = jobs.get_blast_job(job_id, command="flush_slow_listening")
    with jobs._blast_jobs_lock:
        pending = job.result.slow_listening_pending_choice
        if job.result.status != "waiting" or pending is None:
            raise HTTPException(
                status_code=409, detail="Slow Listening job is not waiting for a choice"
            )
        submitted_order = _validate_submission(pending, request)
        job.submitted_choice = request.choice
        job.submitted_order = submitted_order
        job.result.slow_listening_pending_choice = None
        job.result.status = "running"
        job.result.detail = "Slow Listening choice submitted"
        job.choice_event.set()
        return jobs._blast_job_snapshot(job)


def cmd_cancel_slow_listening_job(job_id: str) -> BlastJobResult:
    """Request a clean stop at the next Slow Listening boundary.

    Args:
        job_id: Original validated job id value.

    Returns:
        Original feature response with unchanged fields and validation.

    Raises:
        HTTPException: An original validation or feature error is observed.
    """
    job = jobs.get_blast_job(job_id, command="flush_slow_listening")
    with jobs._blast_jobs_lock:
        if job.result.status not in jobs._ACTIVE_JOB_STATUSES:
            raise HTTPException(
                status_code=409, detail="Slow Listening job is not active"
            )
        job.result.status = "cancelling"
        job.result.slow_listening_pending_choice = None
        job.result.detail = "Stopping Slow Listening flush"
        jobs._append_blast_log_locked(job, job.result.detail)
        job.cancel_event.set()
        job.choice_event.set()
        return jobs._blast_job_snapshot(job)


def _validate_submission(
    pending: SlowListeningPendingChoice, request: SlowListeningChoiceRequest
) -> tuple[str, ...] | None:
    submitted_order: tuple[str, ...] | None = None
    if pending.kind == "track":
        allowed = {
            slow_listening.CHOICE_ADVANCE,
            slow_listening.CHOICE_SKIP,
            slow_listening.CHOICE_QUIT,
        }
        if request.choice not in allowed or request.order:
            raise HTTPException(status_code=400, detail="track choice is not available")
    elif pending.kind == "release_order":
        expected_ids = set(option_ids(pending.releases))
        submitted_order = tuple(request.order)
        if (
            request.choice != "order"
            or len(submitted_order) != len(expected_ids)
            or set(submitted_order) != expected_ids
        ):
            raise HTTPException(
                status_code=400,
                detail="release order must include every option exactly once",
            )
    elif request.choice != "continue" or request.order:
        raise HTTPException(
            status_code=400, detail="completion choice is not available"
        )
    return submitted_order
