"""Validate and present daily mind radio HTTP requests."""

from fastapi import HTTPException
from spotipy import Spotify

from spotify_manager.interfaces.http import jobs
from spotify_manager.interfaces.http.models.jobs import BlastJobResult
from spotify_manager.interfaces.operations import blast_from_past as blast_from_past


def cmd_daily_mind_radio(client: Spotify, dry_run: bool) -> BlastJobResult:
    """Start a background Daily Mind Radio anniversary update.

    Args:
        client: Original validated client value.
        dry_run: Original validated dry run value.

    Returns:
        Original feature response with unchanged fields and validation.

    Raises:
        HTTPException: An original validation or feature error is observed.
    """
    try:
        playlist_id = blast_from_past.parse_playlist_id(
            jobs.Settings().daily_mind_radio_playlist,
            setting_name="DAILY_MIND_RADIO_PLAYLIST",
        )
    except blast_from_past.BlastFromPastConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return jobs.start_daily_mind_radio_job(client, playlist_id, dry_run)


def cmd_active_daily_mind_radio_jobs() -> list[BlastJobResult]:
    """Return active Daily Mind Radio jobs for web reload reconnection.

    Returns:
        Original feature response with unchanged fields and validation.
    """
    return jobs._active_playlist_jobs("daily_mind_radio")


def cmd_daily_mind_radio_job(job_id: str) -> BlastJobResult:
    """Return current progress for one Daily Mind Radio job.

    Args:
        job_id: Original validated job id value.

    Returns:
        Original feature response with unchanged fields and validation.
    """
    job = jobs.get_blast_job(job_id, command="daily_mind_radio")
    with jobs._blast_jobs_lock:
        return jobs._blast_job_snapshot(job)


def cmd_cancel_daily_mind_radio_job(job_id: str) -> BlastJobResult:
    """Stop Daily Mind Radio at the next bounded network-operation boundary.

    Args:
        job_id: Original validated job id value.

    Returns:
        Original feature response with unchanged fields and validation.
    """
    return jobs._cancel_simple_playlist_job(
        job_id, command="daily_mind_radio", detail="Stopping Daily Mind Radio"
    )
