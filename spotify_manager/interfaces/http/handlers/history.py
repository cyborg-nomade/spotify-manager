"""Validate and present history HTTP requests."""

from fastapi import HTTPException

from spotify_manager.core.library_data import LibraryDataError
from spotify_manager.core.library_data.service import ArtifactStatus
from spotify_manager.interfaces.http import jobs
from spotify_manager.interfaces.http.models.common import LibraryMirrorFilesStatus
from spotify_manager.interfaces.http.models.common import ServerFileStatus
from spotify_manager.interfaces.http.models.jobs import BlastJobResult
from spotify_manager.interfaces.operations import found_art as found_art


def cmd_update_scrobble_history(dry_run: bool, full_rebuild: bool) -> BlastJobResult:
    """Start a background refresh of the shared Last.fm scrobble record.

    Args:
        dry_run: Original validated dry run value.
        full_rebuild: Original validated full rebuild value.

    Returns:
        Original feature response with unchanged fields and validation.

    Raises:
        HTTPException: An original validation or feature error is observed.
    """
    configuration = jobs.Settings()
    try:
        api_key, username = found_art.validate_lastfm_configuration(
            configuration.lastfm_api_key, configuration.lastfm_username
        )
    except found_art.FoundArtConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return jobs.start_scrobble_history_job(
        api_key, username, dry_run=dry_run, full_rebuild=full_rebuild
    )


def library_mirror_files_status() -> LibraryMirrorFilesStatus:
    """Return durable update metadata for all canonical data files.

    Returns:
        Original feature response with unchanged fields and validation.
    """
    try:
        statuses = jobs.get_library_data_service().statuses()
    except LibraryDataError:
        return _local_files_status()
    if not any(item.exists for item in statuses):
        return _local_files_status()
    return _durable_files_status(statuses)


def cmd_active_scrobble_history_jobs() -> list[BlastJobResult]:
    """Return active history refreshes for page-reload reconnection.

    Returns:
        Original feature response with unchanged fields and validation.
    """
    return jobs._active_playlist_jobs("update_scrobble_history")


def cmd_scrobble_history_job(job_id: str) -> BlastJobResult:
    """Return the current state and logs for one history refresh.

    Args:
        job_id: Original validated job id value.

    Returns:
        Original feature response with unchanged fields and validation.
    """
    job = jobs.get_blast_job(job_id, command="update_scrobble_history")
    with jobs._blast_jobs_lock:
        return jobs._blast_job_snapshot(job)


def cmd_cancel_scrobble_history_job(job_id: str) -> BlastJobResult:
    """Request a clean history stop before its next persistence boundary.

    Args:
        job_id: Original validated job id value.

    Returns:
        Original feature response with unchanged fields and validation.
    """
    return jobs._cancel_simple_playlist_job(
        job_id,
        command="update_scrobble_history",
        detail="Stopping Last.fm scrobble history update",
    )


def _local_files_status() -> LibraryMirrorFilesStatus:
    files = []
    for path in jobs.LIBRARY_MIRROR_FILE_PATHS:
        files.append(jobs._server_file_status(path))
    return LibraryMirrorFilesStatus(files=files)


def _durable_files_status(
    statuses: tuple[ArtifactStatus, ...],
) -> LibraryMirrorFilesStatus:
    files = []
    for item in statuses:
        files.append(
            ServerFileStatus(
                filename=item.filename, exists=item.exists, updated_at=item.updated_at
            )
        )
    return LibraryMirrorFilesStatus(files=files)
