"""Validate and present analysis HTTP requests."""

from fastapi import HTTPException

from spotify_manager.application.ports.spotify_client import SpotifyClient as Spotify
from spotify_manager.interfaces.http import jobs
from spotify_manager.interfaces.http.models.analysis import AnalysisJobResult
from spotify_manager.interfaces.operations import analyse_library as library_analysis


async def cmd_analyse_library_async() -> AnalysisJobResult:
    """Start an export-only ``*_async`` library analysis.

    Returns:
        Original feature response with unchanged fields and validation.
    """
    return await jobs.start_analysis_job("async")


async def cmd_analyse_library_sync(client: Spotify) -> AnalysisJobResult:
    """Start a live-only ``*_sync`` library analysis.

    Args:
        client: Original validated client value.

    Returns:
        Original feature response with unchanged fields and validation.
    """
    return await jobs.start_analysis_job("sync", client)


async def cmd_refresh_library_mirrors(
    client: Spotify, full_rebuild: bool
) -> AnalysisJobResult:
    """Refresh canonical saved-album and liked-track mirrors from Spotify.

    Args:
        client: Original validated client value.
        full_rebuild: Original validated full rebuild value.

    Returns:
        Original feature response with unchanged fields and validation.
    """
    return await jobs.start_analysis_job("mirrors", client, full_rebuild=full_rebuild)


async def cmd_refresh_library_mirror_resource(
    resource: library_analysis.ResourceName, client: Spotify, full_rebuild: bool
) -> AnalysisJobResult:
    """Refresh one canonical Spotify mirror with independent progress.

    Args:
        resource: Original validated resource value.
        client: Original validated client value.
        full_rebuild: Original validated full rebuild value.

    Returns:
        Original feature response with unchanged fields and validation.
    """
    return await jobs.start_analysis_job(
        "mirrors", client, full_rebuild=full_rebuild, mirror_resource=resource
    )


def cmd_active_library_analysis_jobs() -> list[AnalysisJobResult]:
    """Return active analyses so the web UI can reconnect after a reload.

    Returns:
        Original feature response with unchanged fields and validation.
    """
    return jobs._active_analysis_jobs()


def cmd_library_analysis_job(job_id: str) -> AnalysisJobResult:
    """Return current progress for one library analysis job.

    Args:
        job_id: Original validated job id value.

    Returns:
        Original feature response with unchanged fields and validation.
    """
    job = jobs.get_analysis_job(job_id)
    with jobs._analysis_jobs_lock:
        return jobs._job_snapshot(job)


def cmd_cancel_library_analysis_job(job_id: str) -> AnalysisJobResult:
    """Request a clean stop at the next durable analysis boundary.

    Args:
        job_id: Original validated job id value.

    Returns:
        Original feature response with unchanged fields and validation.

    Raises:
        HTTPException: An original validation or feature error is observed.
    """
    job = jobs.get_analysis_job(job_id)
    with jobs._analysis_jobs_lock:
        if job.result.status not in jobs._ACTIVE_JOB_STATUSES:
            raise HTTPException(status_code=409, detail="analysis job is not active")
        job.cancel_event.set()
        job.result.status = "cancelling"
        job.result.detail = "Saving progress and stopping"
        jobs._append_job_log_locked(job, "Cancellation requested; saving progress.")
        return jobs._job_snapshot(job)
