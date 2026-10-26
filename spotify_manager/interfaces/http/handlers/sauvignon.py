"""Validate and present sauvignon HTTP requests."""

from fastapi import HTTPException
from spotipy import Spotify

from spotify_manager.interfaces import sauvignon_operations as sauvignon
from spotify_manager.interfaces.http import jobs
from spotify_manager.interfaces.http.models.jobs import BlastJobResult
from spotify_manager.interfaces.http.models.recommendations import (
    SauvignonChoiceRequest,
)
from spotify_manager.interfaces.http.validation import option_ids
from spotify_manager.interfaces.operations import found_art as found_art


def cmd_fill_sauvignon_from_lastfm(
    client: Spotify,
    count: int | None,
    max_playlist_length: int | None,
    seed_count: int,
    dry_run: bool,
) -> BlastJobResult:
    """Start reconnectable Last.fm album discovery for Sauvignon.

    Args:
        client: Original validated client value.
        count: Original validated count value.
        max_playlist_length: Original validated max playlist length value.
        seed_count: Original validated seed count value.
        dry_run: Original validated dry run value.

    Returns:
        Original feature response with unchanged fields and validation.

    Raises:
        HTTPException: An original validation or feature error is observed.
    """
    if count is not None and max_playlist_length is not None:
        raise HTTPException(
            status_code=400,
            detail="use either count or maximum playlist length, not both",
        )
    configuration = jobs.Settings()
    try:
        playlist_id = sauvignon.parse_playlist_id(
            configuration.sauvignon_terre_neuve_playlist
        )
        api_key, username = found_art.validate_lastfm_configuration(
            configuration.lastfm_api_key, configuration.lastfm_username
        )
    except (sauvignon.SauvignonConfigError, found_art.FoundArtConfigError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    effective_maximum = (
        sauvignon.DEFAULT_MAX_PLAYLIST_LENGTH
        if count is None and max_playlist_length is None
        else max_playlist_length
    )
    return jobs.start_sauvignon_job(
        client,
        playlist_id,
        api_key,
        username,
        count=count,
        max_playlist_length=effective_maximum,
        seed_count=seed_count,
        dry_run=dry_run,
    )


def cmd_active_sauvignon_jobs() -> list[BlastJobResult]:
    """Return active Sauvignon jobs so the UI can reconnect after reload.

    Returns:
        Original feature response with unchanged fields and validation.
    """
    return jobs._active_playlist_jobs("fill_sauvignon_from_lastfm")


def cmd_sauvignon_job(job_id: str) -> BlastJobResult:
    """Return Sauvignon progress and any pending album-edition choice.

    Args:
        job_id: Original validated job id value.

    Returns:
        Original feature response with unchanged fields and validation.
    """
    job = jobs.get_blast_job(job_id, command="fill_sauvignon_from_lastfm")
    with jobs._blast_jobs_lock:
        return jobs._blast_job_snapshot(job)


def cmd_choose_sauvignon_album(
    job_id: str, request: SauvignonChoiceRequest
) -> BlastJobResult:
    """Submit one ambiguous Spotify album edition, skip, or quit choice.

    Args:
        job_id: Original validated job id value.
        request: Original validated request value.

    Returns:
        Original feature response with unchanged fields and validation.

    Raises:
        HTTPException: An original validation or feature error is observed.
    """
    job = jobs.get_blast_job(job_id, command="fill_sauvignon_from_lastfm")
    with jobs._blast_jobs_lock:
        pending = job.result.sauvignon_pending_choice
        if job.result.status != "waiting" or pending is None:
            raise HTTPException(
                status_code=409,
                detail="Sauvignon discovery is not waiting for an album choice",
            )
        allowed = {
            sauvignon.CHOICE_SKIP,
            sauvignon.CHOICE_QUIT,
            *option_ids(pending.options),
        }
        if request.choice not in allowed:
            raise HTTPException(status_code=400, detail="album choice is not available")
        job.submitted_choice = request.choice
        job.result.sauvignon_pending_choice = None
        job.result.status = "running"
        job.result.detail = "Sauvignon album choice submitted"
        job.choice_event.set()
        return jobs._blast_job_snapshot(job)


def cmd_cancel_sauvignon_job(job_id: str) -> BlastJobResult:
    """Stop Sauvignon discovery at its next safe boundary.

    Args:
        job_id: Original validated job id value.

    Returns:
        Original feature response with unchanged fields and validation.

    Raises:
        HTTPException: An original validation or feature error is observed.
    """
    job = jobs.get_blast_job(job_id, command="fill_sauvignon_from_lastfm")
    with jobs._blast_jobs_lock:
        if job.result.status not in jobs._ACTIVE_JOB_STATUSES:
            raise HTTPException(
                status_code=409, detail="Sauvignon discovery job is not active"
            )
        job.result.status = "cancelling"
        job.result.sauvignon_pending_choice = None
        job.result.detail = "Stopping Sauvignon album discovery"
        jobs._append_blast_log_locked(job, job.result.detail)
        job.cancel_event.set()
        job.choice_event.set()
        return jobs._blast_job_snapshot(job)
