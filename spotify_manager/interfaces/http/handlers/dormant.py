"""Validate and present dormant HTTP requests."""

from fastapi import HTTPException

from spotify_manager.application.ports.spotify_client import SpotifyClient as Spotify
from spotify_manager.interfaces.http import jobs
from spotify_manager.interfaces.http.models.jobs import BlastJobResult
from spotify_manager.interfaces.operations import blast_from_past as blast_from_past


async def cmd_blast_from_the_past_artists(
    client: Spotify, count: int, dry_run: bool
) -> BlastJobResult:
    """Start an alphabetic dormant-artist recovery update.

    Args:
        client: Original validated client value.
        count: Original validated count value.
        dry_run: Original validated dry run value.

    Returns:
        Original feature response with unchanged fields and validation.

    Raises:
        HTTPException: An original validation or feature error is observed.
    """
    try:
        playlist_id = blast_from_past.parse_playlist_id(
            jobs.Settings().blast_from_the_past_playlist
        )
    except blast_from_past.BlastFromPastConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return await jobs.start_blast_artist_job(client, playlist_id, count, dry_run)


def cmd_active_blast_artist_jobs() -> list[BlastJobResult]:
    """Return the active dormant-artist job for browser reconnection.

    Returns:
        Original feature response with unchanged fields and validation.
    """
    return jobs._active_playlist_jobs("blast_from_the_past_artists")


def cmd_blast_artist_job(job_id: str) -> BlastJobResult:
    """Return current progress for one dormant-artist job.

    Args:
        job_id: Original validated job id value.

    Returns:
        Original feature response with unchanged fields and validation.
    """
    job = jobs.get_blast_job(job_id, command="blast_from_the_past_artists")
    with jobs._blast_jobs_lock:
        return jobs._blast_job_snapshot(job)


def cmd_cancel_blast_artist_job(job_id: str) -> BlastJobResult:
    """Cancel dormant-artist recovery at the next safe boundary.

    Args:
        job_id: Original validated job id value.

    Returns:
        Original feature response with unchanged fields and validation.
    """
    return jobs._cancel_simple_playlist_job(
        job_id,
        command="blast_from_the_past_artists",
        detail="Stopping dormant-artist recovery",
    )
