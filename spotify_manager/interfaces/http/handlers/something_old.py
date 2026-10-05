"""Validate and present something old HTTP requests."""

from fastapi import HTTPException
from spotipy import Spotify

from spotify_manager.interfaces.http import jobs
from spotify_manager.interfaces.http.models.jobs import BlastJobResult
from spotify_manager.interfaces.http.models.something_old import (
    SomethingOldChoiceRequest,
)
from spotify_manager.interfaces.http.models.something_old import (
    SomethingOldPendingChoice,
)
from spotify_manager.interfaces.http.validation import option_ids
from spotify_manager.interfaces.operations import found_art as found_art
from spotify_manager.interfaces.operations import something_old as something_old


def cmd_something_old(client: Spotify, dry_run: bool) -> BlastJobResult:
    """Start an interactive Something Old selection with reconnectable state.

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
        playlist_id = something_old.parse_playlist_id(
            configuration.something_old_new_playlist
        )
        api_key, username = found_art.validate_lastfm_configuration(
            configuration.lastfm_api_key, configuration.lastfm_username
        )
    except (
        something_old.SomethingOldConfigError,
        found_art.FoundArtConfigError,
    ) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return jobs.start_something_old_job(
        client, playlist_id, api_key, username, dry_run=dry_run
    )


def cmd_active_something_old_jobs() -> list[BlastJobResult]:
    """Return active Something Old jobs for page-reload reconnection.

    Returns:
        Original feature response with unchanged fields and validation.
    """
    return jobs._active_playlist_jobs("something_old")


def cmd_something_old_job(job_id: str) -> BlastJobResult:
    """Return current Something Old progress and any pending choice.

    Args:
        job_id: Original validated job id value.

    Returns:
        Original feature response with unchanged fields and validation.
    """
    job = jobs.get_blast_job(job_id, command="something_old")
    with jobs._blast_jobs_lock:
        return jobs._blast_job_snapshot(job)


def cmd_choose_something_old(
    job_id: str, request: SomethingOldChoiceRequest
) -> BlastJobResult:
    """Submit an exact artist, source mode, album/EP, or quit choice.

    Args:
        job_id: Original validated job id value.
        request: Original validated request value.

    Returns:
        Original feature response with unchanged fields and validation.

    Raises:
        HTTPException: An original validation or feature error is observed.
    """
    job = jobs.get_blast_job(job_id, command="something_old")
    with jobs._blast_jobs_lock:
        pending = job.result.something_old_pending_choice
        if job.result.status != "waiting" or pending is None:
            raise HTTPException(
                status_code=409, detail="Something Old job is not waiting for a choice"
            )
        _validate_submission(pending, request)
        job.submitted_choice = request.choice
        job.result.something_old_pending_choice = None
        job.result.status = "running"
        job.result.detail = "Something Old choice submitted"
        job.choice_event.set()
        return jobs._blast_job_snapshot(job)


def cmd_cancel_something_old_job(job_id: str) -> BlastJobResult:
    """Request a clean stop at the next Something Old boundary.

    Args:
        job_id: Original validated job id value.

    Returns:
        Original feature response with unchanged fields and validation.

    Raises:
        HTTPException: An original validation or feature error is observed.
    """
    job = jobs.get_blast_job(job_id, command="something_old")
    with jobs._blast_jobs_lock:
        if job.result.status not in jobs._ACTIVE_JOB_STATUSES:
            raise HTTPException(
                status_code=409, detail="Something Old job is not active"
            )
        job.result.status = "cancelling"
        job.result.something_old_pending_choice = None
        job.result.detail = "Stopping Something Old"
        jobs._append_blast_log_locked(job, job.result.detail)
        job.cancel_event.set()
        job.choice_event.set()
        return jobs._blast_job_snapshot(job)


def _validate_submission(
    pending: SomethingOldPendingChoice, request: SomethingOldChoiceRequest
) -> None:
    if pending.kind == "artist":
        allowed = {"quit", *option_ids(pending.artist_candidates)}
    elif pending.kind == "mode":
        allowed = {"lastfm_top_tracks", "spotify_top_tracks", "album", "quit"}
    else:
        allowed = {"quit", *option_ids(pending.releases)}
    if request.choice not in allowed:
        raise HTTPException(
            status_code=400, detail="Something Old choice is not available"
        )
