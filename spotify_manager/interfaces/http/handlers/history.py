"""Original history HTTP validation and job interactions."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from fastapi import HTTPException

from spotify_manager.core.library_data import LibraryDataError
from spotify_manager.core.library_data.service import ArtifactStatus
from spotify_manager.core.library_data.service import LibraryDataService
from spotify_manager.interfaces.http.job_records import PlaylistJob as _BlastJob
from spotify_manager.interfaces.http.models.common import LibraryMirrorFilesStatus
from spotify_manager.interfaces.http.models.common import ServerFileStatus
from spotify_manager.interfaces.http.models.jobs import BlastJobResult
from spotify_manager.routines import found_art
from spotify_manager.settings import Settings


@dataclass(kw_only=True)
class HistoryHandlers:
    """Validate and present one feature through explicit facade dependencies.

    Args:
        LIBRARY_MIRROR_FILE_PATHS: Existing overridable feature dependency.
        Settings: Existing overridable feature dependency.
        _active_playlist_jobs: Existing overridable feature dependency.
        _blast_job_snapshot: Existing overridable feature dependency.
        _blast_jobs_lock: Existing overridable feature dependency.
        _cancel_simple_playlist_job: Existing overridable feature dependency.
        _server_file_status: Existing overridable feature dependency.
        get_blast_job: Existing overridable feature dependency.
        get_library_data_service: Existing overridable feature dependency.
        start_scrobble_history_job: Existing overridable feature dependency.
    """

    LIBRARY_MIRROR_FILE_PATHS: tuple[Path, ...]
    Settings: type[Settings]
    _active_playlist_jobs: Callable[..., list[BlastJobResult]]
    _blast_job_snapshot: Callable[..., BlastJobResult]
    _blast_jobs_lock: Lock
    _cancel_simple_playlist_job: Callable[..., BlastJobResult]
    _server_file_status: Callable[..., ServerFileStatus]
    get_blast_job: Callable[..., _BlastJob]
    get_library_data_service: Callable[..., LibraryDataService]
    start_scrobble_history_job: Callable[..., BlastJobResult]

    def cmd_update_scrobble_history(
        self, dry_run: bool, full_rebuild: bool
    ) -> BlastJobResult:
        """Start a background refresh of the shared Last.fm scrobble record.

        Args:
            dry_run: Original validated dry run value.
            full_rebuild: Original validated full rebuild value.

            Returns:
            Original feature response with unchanged fields and validation.

            Raises:
            HTTPException: An original validation or feature error is observed.
        """
        configuration = self.Settings()
        try:
            api_key, username = found_art.validate_lastfm_configuration(
                configuration.lastfm_api_key, configuration.lastfm_username
            )
        except found_art.FoundArtConfigError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return self.start_scrobble_history_job(
            api_key, username, dry_run=dry_run, full_rebuild=full_rebuild
        )

    def library_mirror_files_status(self) -> LibraryMirrorFilesStatus:
        """Return durable update metadata for all canonical data files.

        Returns:
            Original feature response with unchanged fields and validation.
        """
        try:
            statuses = self.get_library_data_service().statuses()
        except LibraryDataError:
            return self._local_files_status()
        if not any(item.exists for item in statuses):
            return self._local_files_status()
        return self._durable_files_status(statuses)

    def cmd_active_scrobble_history_jobs(self) -> list[BlastJobResult]:
        """Return active history refreshes for page-reload reconnection.

        Returns:
            Original feature response with unchanged fields and validation.
        """
        return self._active_playlist_jobs("update_scrobble_history")

    def cmd_scrobble_history_job(self, job_id: str) -> BlastJobResult:
        """Return the current state and logs for one history refresh.

        Args:
            job_id: Original validated job id value.

            Returns:
            Original feature response with unchanged fields and validation.
        """
        job = self.get_blast_job(job_id, command="update_scrobble_history")
        with self._blast_jobs_lock:
            return self._blast_job_snapshot(job)

    def cmd_cancel_scrobble_history_job(self, job_id: str) -> BlastJobResult:
        """Request a clean history stop before its next persistence boundary.

        Args:
            job_id: Original validated job id value.

            Returns:
            Original feature response with unchanged fields and validation.
        """
        return self._cancel_simple_playlist_job(
            job_id,
            command=("update_scrobble_history"),
            detail=("Stopping Last.fm scrobble history update"),
        )

    def _local_files_status(self) -> LibraryMirrorFilesStatus:
        files = []
        for path in self.LIBRARY_MIRROR_FILE_PATHS:
            files.append(self._server_file_status(path))
        return LibraryMirrorFilesStatus(files=files)

    def _durable_files_status(
        self, statuses: tuple[ArtifactStatus, ...]
    ) -> LibraryMirrorFilesStatus:
        files = []
        for item in statuses:
            files.append(
                ServerFileStatus(
                    filename=item.filename,
                    exists=item.exists,
                    updated_at=item.updated_at,
                )
            )
        return LibraryMirrorFilesStatus(files=files)
