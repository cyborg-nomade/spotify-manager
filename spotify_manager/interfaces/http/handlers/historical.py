"""Validate and present historical HTTP requests."""

from fastapi import HTTPException

from spotify_manager.application.ports.spotify_client import SpotifyClient as Spotify
from spotify_manager.interfaces.http import jobs
from spotify_manager.interfaces.http.models.jobs import BlastJobResult
from spotify_manager.interfaces.operations import blast_from_past as blast_from_past


async def cmd_blast_from_the_past(
    client: Spotify, count: int | None, max_playlist_length: int | None, dry_run: bool
) -> BlastJobResult:
    """Start a background Friday-routine playlist update.

    Args:
        client: Original validated client value.
        count: Original validated count value.
        max_playlist_length: Original validated max playlist length value.
        dry_run: Original validated dry run value.

    Returns:
        Original feature response with unchanged fields and validation.

    Raises:
        HTTPException: An original validation or feature error is observed.
    """
    if count is not None and max_playlist_length is not None:
        raise HTTPException(
            status_code=400, detail="use either count or max_playlist_length, not both"
        )
    effective_count = 10 if count is None and max_playlist_length is None else count
    try:
        playlist_id = blast_from_past.parse_playlist_id(
            jobs.Settings().blast_from_the_past_playlist
        )
    except blast_from_past.BlastFromPastConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return await jobs.start_blast_job(
        client, playlist_id, effective_count, max_playlist_length, dry_run
    )


def cmd_active_blast_jobs() -> list[BlastJobResult]:
    """Return active playlist jobs so the web UI can reconnect after reload.

    Returns:
        Original feature response with unchanged fields and validation.
    """
    return jobs._active_playlist_jobs("blast_from_the_past")


def cmd_blast_job(job_id: str) -> BlastJobResult:
    """Return current progress for one playlist job.

    Args:
        job_id: Original validated job id value.

    Returns:
        Original feature response with unchanged fields and validation.
    """
    job = jobs.get_blast_job(job_id, command="blast_from_the_past")
    with jobs._blast_jobs_lock:
        return jobs._blast_job_snapshot(job)


def cmd_cancel_blast_job(job_id: str) -> BlastJobResult:
    """Stop a Blast job at the next bounded network-operation boundary.

    Args:
        job_id: Original validated job id value.

    Returns:
        Original feature response with unchanged fields and validation.
    """
    return jobs._cancel_simple_playlist_job(
        job_id, command="blast_from_the_past", detail="Stopping A blast from the past"
    )
