"""Original analysis HTTP validation and job interactions."""

from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock

from fastapi import HTTPException
from spotipy import Spotify

from spotify_manager.interfaces.http.job_records import AnalysisJob as _AnalysisJob
from spotify_manager.interfaces.http.models.analysis import AnalysisJobResult
from spotify_manager.routines import analyse_library as library_analysis


@dataclass(kw_only=True)
class AnalysisHandlers:
    """Validate and present one feature through explicit facade dependencies.

    Args:
        _ACTIVE_JOB_STATUSES: Existing overridable feature dependency.
        _active_analysis_jobs: Existing overridable feature dependency.
        _analysis_jobs_lock: Existing overridable feature dependency.
        _append_job_log_locked: Existing overridable feature dependency.
        _job_snapshot: Existing overridable feature dependency.
        get_analysis_job: Existing overridable feature dependency.
        start_analysis_job: Existing overridable feature dependency.
    """

    _ACTIVE_JOB_STATUSES: set[str]
    _active_analysis_jobs: Callable[..., list[AnalysisJobResult]]
    _analysis_jobs_lock: Lock
    _append_job_log_locked: Callable[..., None]
    _job_snapshot: Callable[..., AnalysisJobResult]
    get_analysis_job: Callable[..., _AnalysisJob]
    start_analysis_job: Callable[..., AnalysisJobResult]

    def cmd_analyse_library_async(self) -> AnalysisJobResult:
        """Start an export-only ``*_async`` library analysis.

        Returns:
            Original feature response with unchanged fields and validation.
        """
        return self.start_analysis_job("async")

    def cmd_analyse_library_sync(self, client: Spotify) -> AnalysisJobResult:
        """Start a live-only ``*_sync`` library analysis.

        Args:
            client: Original validated client value.

            Returns:
            Original feature response with unchanged fields and validation.
        """
        return self.start_analysis_job("sync", client)

    def cmd_refresh_library_mirrors(
        self, client: Spotify, full_rebuild: bool
    ) -> AnalysisJobResult:
        """Refresh canonical saved-album and liked-track mirrors from Spotify.

        Args:
            client: Original validated client value.
            full_rebuild: Original validated full rebuild value.

            Returns:
            Original feature response with unchanged fields and validation.
        """
        return self.start_analysis_job("mirrors", client, full_rebuild=full_rebuild)

    def cmd_refresh_library_mirror_resource(
        self,
        resource: library_analysis.ResourceName,
        client: Spotify,
        full_rebuild: bool,
    ) -> AnalysisJobResult:
        """Refresh one canonical Spotify mirror with independent progress.

        Args:
            resource: Original validated resource value.
            client: Original validated client value.
            full_rebuild: Original validated full rebuild value.

            Returns:
            Original feature response with unchanged fields and validation.
        """
        return self.start_analysis_job(
            ("mirrors"), client, full_rebuild=full_rebuild, mirror_resource=resource
        )

    def cmd_active_library_analysis_jobs(self) -> list[AnalysisJobResult]:
        """Return active analyses so the web UI can reconnect after a reload.

        Returns:
            Original feature response with unchanged fields and validation.
        """
        return self._active_analysis_jobs()

    def cmd_library_analysis_job(self, job_id: str) -> AnalysisJobResult:
        """Return current progress for one library analysis job.

        Args:
            job_id: Original validated job id value.

            Returns:
            Original feature response with unchanged fields and validation.
        """
        job = self.get_analysis_job(job_id)
        with self._analysis_jobs_lock:
            return self._job_snapshot(job)

    def cmd_cancel_library_analysis_job(self, job_id: str) -> AnalysisJobResult:
        """Request a clean stop at the next durable analysis boundary.

        Args:
            job_id: Original validated job id value.

            Returns:
            Original feature response with unchanged fields and validation.

            Raises:
            HTTPException: An original validation or feature error is observed.
        """
        job = self.get_analysis_job(job_id)
        with self._analysis_jobs_lock:
            if job.result.status not in self._ACTIVE_JOB_STATUSES:
                raise HTTPException(
                    status_code=409, detail=("analysis job is not active")
                )
            job.cancel_event.set()
            job.result.status = "cancelling"
            job.result.detail = "Saving progress and stopping"
            self._append_job_log_locked(job, "Cancellation requested; saving progress.")
            return self._job_snapshot(job)
