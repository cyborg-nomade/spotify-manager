"""Validate and present queue fill HTTP requests."""

from fastapi import HTTPException

from spotify_manager.application.ports.spotify_client import SpotifyClient as Spotify
from spotify_manager.interfaces.http import jobs
from spotify_manager.interfaces.http.models.jobs import BlastJobResult
from spotify_manager.interfaces.http.models.queue import QueueChoiceRequest
from spotify_manager.interfaces.http.validation import option_ids
from spotify_manager.interfaces.operations import found_art as found_art
from spotify_manager.interfaces.operations import the_queue as the_queue


async def cmd_fill_queue_from_lastfm(
    client: Spotify,
    count: int | None,
    max_playlist_length: int | None,
    seed_count: int,
    dry_run: bool,
) -> BlastJobResult:
    """Start reconnectable Last.fm artist discovery for The Queue.

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
    playlists = jobs._configured_queue_playlists()
    try:
        api_key, username = found_art.validate_lastfm_configuration(
            configuration.lastfm_api_key, configuration.lastfm_username
        )
    except found_art.FoundArtConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    effective_count = (
        the_queue.DEFAULT_COUNT
        if count is None and max_playlist_length is None
        else count
    )
    return await jobs.start_queue_fill_job(
        client,
        playlists,
        api_key,
        username,
        count=effective_count,
        max_playlist_length=max_playlist_length,
        seed_count=seed_count,
        dry_run=dry_run,
    )


def cmd_active_queue_fill_jobs() -> list[BlastJobResult]:
    """Return active Queue fill jobs so the UI can reconnect after reload.

    Returns:
        Original feature response with unchanged fields and validation.
    """
    return jobs._active_playlist_jobs("fill_queue_from_lastfm")


def cmd_queue_fill_job(job_id: str) -> BlastJobResult:
    """Return Queue fill progress and any pending artist mapping.

    Args:
        job_id: Original validated job id value.

    Returns:
        Original feature response with unchanged fields and validation.
    """
    job = jobs.get_blast_job(job_id, command="fill_queue_from_lastfm")
    with jobs._blast_jobs_lock:
        return jobs._blast_job_snapshot(job)


def cmd_choose_queue_artist(job_id: str, request: QueueChoiceRequest) -> BlastJobResult:
    """Submit one Spotify artist mapping, custom search, skip, or quit.

    Args:
        job_id: Original validated job id value.
        request: Original validated request value.

    Returns:
        Original feature response with unchanged fields and validation.

    Raises:
        HTTPException: An original validation or feature error is observed.
    """
    job = jobs.get_blast_job(job_id, command="fill_queue_from_lastfm")
    with jobs._blast_jobs_lock:
        pending = job.result.queue_pending_choice
        if job.result.status != "waiting" or pending is None:
            raise HTTPException(
                status_code=409,
                detail="Queue fill is not waiting for an artist mapping",
            )
        allowed = {
            the_queue.CHOICE_SKIP,
            the_queue.CHOICE_QUIT,
            *option_ids(pending.candidates),
        }
        custom_search = request.choice.startswith(the_queue.CHOICE_SEARCH_PREFIX)
        if custom_search:
            custom_search = bool(
                request.choice.removeprefix(the_queue.CHOICE_SEARCH_PREFIX).strip()
            )
        if request.choice not in allowed and (not custom_search):
            raise HTTPException(
                status_code=400, detail="artist choice is not available"
            )
        job.submitted_choice = request.choice
        job.result.queue_pending_choice = None
        job.result.status = "running"
        job.result.detail = "Queue artist choice submitted"
        job.choice_event.set()
        return jobs._blast_job_snapshot(job)


def cmd_cancel_queue_fill_job(job_id: str) -> BlastJobResult:
    """Stop Queue artist discovery at its next safe boundary.

    Args:
        job_id: Original validated job id value.

    Returns:
        Original feature response with unchanged fields and validation.
    """
    return jobs._cancel_queue_job(job_id, "fill_queue_from_lastfm", "Queue fill")
