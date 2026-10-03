"""Original queue 3 HTTP validation and job interactions."""

from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock

from fastapi import HTTPException
from spotipy import Spotify

from spotify_manager.interfaces.http.job_records import PlaylistJob as _BlastJob
from spotify_manager.interfaces.http.models.discovery import Queue3ChoiceRequest
from spotify_manager.interfaces.http.models.jobs import BlastJobResult
from spotify_manager.interfaces.http.validation import option_ids
from spotify_manager.routines import queue_3
from spotify_manager.settings import Settings


@dataclass(kw_only=True)
class Queue3Handlers:
    """Validate and present one feature through explicit facade dependencies.

    Args:
        Settings: Existing overridable feature dependency.
        _ACTIVE_JOB_STATUSES: Existing overridable feature dependency.
        _active_playlist_jobs: Existing overridable feature dependency.
        _append_blast_log_locked: Existing overridable feature dependency.
        _blast_job_snapshot: Existing overridable feature dependency.
        _blast_jobs_lock: Existing overridable feature dependency.
        get_blast_job: Existing overridable feature dependency.
        start_queue_3_job: Existing overridable feature dependency.
    """

    Settings: type[Settings]
    _ACTIVE_JOB_STATUSES: set[str]
    _active_playlist_jobs: Callable[..., list[BlastJobResult]]
    _append_blast_log_locked: Callable[..., None]
    _blast_job_snapshot: Callable[..., BlastJobResult]
    _blast_jobs_lock: Lock
    get_blast_job: Callable[..., _BlastJob]
    start_queue_3_job: Callable[..., BlastJobResult]

    def cmd_flush_queue_3(self, client: Spotify, dry_run: bool) -> BlastJobResult:
        """Start an interactive Queue 3 flush with reconnectable web state.

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
            playlist_id = queue_3.parse_playlist_id(configuration.the_queue_3_playlist)
        except queue_3.Queue3ConfigError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return self.start_queue_3_job(client, playlist_id, dry_run=dry_run)

    def cmd_import_queue_3_previous_year(
        self, client: Spotify, dry_run: bool
    ) -> BlastJobResult:
        """Start the annual Queue 3 import without advancing existing artists.

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
            playlist_id = queue_3.parse_playlist_id(configuration.the_queue_3_playlist)
        except queue_3.Queue3ConfigError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return self.start_queue_3_job(
            client, playlist_id, dry_run=dry_run, annual_only=True
        )

    def cmd_active_queue_3_jobs(self) -> list[BlastJobResult]:
        """Return active Queue 3 jobs so the web UI can reconnect after reload.

        Returns:
            Original feature response with unchanged fields and validation.
        """
        return self._active_playlist_jobs("flush_queue_3")

    def cmd_queue_3_job(self, job_id: str) -> BlastJobResult:
        """Return current progress and any pending Queue 3 choice.

        Args:
            job_id: Original validated job id value.

        Returns:
            Original feature response with unchanged fields and validation.
        """
        job = self.get_blast_job(job_id, command="flush_queue_3")
        with self._blast_jobs_lock:
            return self._blast_job_snapshot(job)

    def cmd_choose_queue_3(
        self, job_id: str, request: Queue3ChoiceRequest
    ) -> BlastJobResult:
        """Submit one release, composer-playlist, or quit choice to Queue 3.

        Args:
            job_id: Original validated job id value.
            request: Original validated request value.

        Returns:
            Original feature response with unchanged fields and validation.

        Raises:
            HTTPException: An original validation or feature error is observed.
        """
        job = self.get_blast_job(job_id, command="flush_queue_3")
        with self._blast_jobs_lock:
            pending = job.result.queue_3_pending_choice
            if job.result.status != "waiting" or pending is None:
                raise HTTPException(
                    status_code=409, detail="Queue 3 job is not waiting for a choice"
                )
            if pending.kind == "release":
                allowed = {queue_3.CHOICE_ADVANCE, queue_3.CHOICE_QUIT}
            else:
                allowed = {queue_3.CHOICE_QUIT, *option_ids(pending.playlists)}
            if request.choice not in allowed:
                raise HTTPException(
                    status_code=400, detail="Queue 3 choice is not available"
                )
            job.submitted_choice = request.choice
            job.result.queue_3_pending_choice = None
            job.result.status = "running"
            job.result.detail = "Queue 3 choice submitted"
            job.choice_event.set()
            return self._blast_job_snapshot(job)

    def cmd_cancel_queue_3_job(self, job_id: str) -> BlastJobResult:
        """Request a clean stop at the next Queue 3 processing boundary.

        Args:
            job_id: Original validated job id value.

        Returns:
            Original feature response with unchanged fields and validation.

        Raises:
            HTTPException: An original validation or feature error is observed.
        """
        job = self.get_blast_job(job_id, command="flush_queue_3")
        with self._blast_jobs_lock:
            if job.result.status not in self._ACTIVE_JOB_STATUSES:
                raise HTTPException(status_code=409, detail="Queue 3 job is not active")
            job.result.status = "cancelling"
            job.result.queue_3_pending_choice = None
            job.result.detail = "Stopping Queue 3 flush"
            self._append_blast_log_locked(job, job.result.detail)
            job.cancel_event.set()
            job.choice_event.set()
            return self._blast_job_snapshot(job)
