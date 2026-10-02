"""Original requeue HTTP validation and job interactions."""

from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock

from fastapi import HTTPException
from spotipy import Spotify

from spotify_manager.interfaces.http.job_records import PlaylistJob as _BlastJob
from spotify_manager.interfaces.http.models.jobs import BlastJobResult
from spotify_manager.routines import requeue_for_a_dream
from spotify_manager.settings import Settings


@dataclass(kw_only=True)
class RequeueHandlers:
    """Validate and present one feature through explicit facade dependencies.

    Args:
        Settings: Existing overridable feature dependency.
        _ACTIVE_JOB_STATUSES: Existing overridable feature dependency.
        _active_playlist_jobs: Existing overridable feature dependency.
        _append_blast_log_locked: Existing overridable feature dependency.
        _blast_job_snapshot: Existing overridable feature dependency.
        _blast_jobs_lock: Existing overridable feature dependency.
        get_blast_job: Existing overridable feature dependency.
        start_requeue_for_a_dream_job: Existing overridable feature dependency.
    """

    Settings: type[Settings]
    _ACTIVE_JOB_STATUSES: set[str]
    _active_playlist_jobs: Callable[..., list[BlastJobResult]]
    _append_blast_log_locked: Callable[..., None]
    _blast_job_snapshot: Callable[..., BlastJobResult]
    _blast_jobs_lock: Lock
    get_blast_job: Callable[..., _BlastJob]
    start_requeue_for_a_dream_job: Callable[..., BlastJobResult]

    def cmd_flush_requeue_for_a_dream(
        self, client: Spotify, dry_run: bool
    ) -> BlastJobResult:
        """Start a reconnectable Requeue for a Dream transition.

        Args:
            client: Original validated client value.
            dry_run: Original validated dry run value.

            Returns:
            Original feature response with unchanged fields and validation.

            Raises:
            HTTPException: An original validation or feature error is observed.
        """
        configuration = self.Settings()
        try:
            playlist_id = requeue_for_a_dream.parse_playlist_id(
                configuration.reqeueue_for_a_dream_playlist
            )
        except requeue_for_a_dream.RequeueForADreamConfigError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return self.start_requeue_for_a_dream_job(client, playlist_id, dry_run=dry_run)

    def cmd_active_requeue_for_a_dream_jobs(self) -> list[BlastJobResult]:
        """Return active Requeue for a Dream jobs after a page reload.

        Returns:
            Original feature response with unchanged fields and validation.
        """
        return self._active_playlist_jobs("flush_requeue_for_a_dream")

    def cmd_requeue_for_a_dream_job(self, job_id: str) -> BlastJobResult:
        """Return the current state and logs for one Requeue transition.

        Args:
            job_id: Original validated job id value.

            Returns:
            Original feature response with unchanged fields and validation.
        """
        job = self.get_blast_job(job_id, command="flush_requeue_for_a_dream")
        with self._blast_jobs_lock:
            return self._blast_job_snapshot(job)

    def cmd_cancel_requeue_for_a_dream_job(self, job_id: str) -> BlastJobResult:
        """Request a clean stop at the next API or retry boundary.

        Args:
            job_id: Original validated job id value.

            Returns:
            Original feature response with unchanged fields and validation.

            Raises:
            HTTPException: An original validation or feature error is observed.
        """
        job = self.get_blast_job(job_id, command="flush_requeue_for_a_dream")
        with self._blast_jobs_lock:
            if job.result.status not in self._ACTIVE_JOB_STATUSES:
                raise HTTPException(
                    status_code=409, detail=("Requeue for a Dream job is not active")
                )
            job.result.status = "cancelling"
            job.result.detail = "Stopping Requeue for a Dream"
            self._append_blast_log_locked(job, job.result.detail)
            job.cancel_event.set()
            return self._blast_job_snapshot(job)
