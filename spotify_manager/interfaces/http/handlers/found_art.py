"""Validate and present found art HTTP requests."""

from fastapi import HTTPException

from spotify_manager.application.ports.spotify_client import SpotifyClient as Spotify
from spotify_manager.interfaces.http import jobs
from spotify_manager.interfaces.http.models.jobs import BlastJobResult
from spotify_manager.interfaces.operations import found_art as found_art


async def cmd_found_art(client: Spotify, count: int) -> BlastJobResult:
    """Start a background Found Art recommendation update.

    Args:
        client: Original validated client value.
        count: Original validated count value.

    Returns:
        Original feature response with unchanged fields and validation.

    Raises:
        HTTPException: An original validation or feature error is observed.
    """
    configuration = jobs.Settings()
    try:
        playlist_id = found_art.parse_found_art_playlist_id(
            configuration.found_art_playlist
        )
        api_key, username = found_art.validate_lastfm_configuration(
            configuration.lastfm_api_key, configuration.lastfm_username
        )
    except found_art.FoundArtConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return await jobs.start_found_art_job(client, playlist_id, api_key, username, count)


def cmd_active_found_art_jobs() -> list[BlastJobResult]:
    """Return active Found Art jobs for web reload reconnection.

    Returns:
        Original feature response with unchanged fields and validation.
    """
    return jobs._active_playlist_jobs("found_art")


def cmd_found_art_job(job_id: str) -> BlastJobResult:
    """Return current progress for one Found Art job.

    Args:
        job_id: Original validated job id value.

    Returns:
        Original feature response with unchanged fields and validation.
    """
    job = jobs.get_blast_job(job_id, command="found_art")
    with jobs._blast_jobs_lock:
        return jobs._blast_job_snapshot(job)
