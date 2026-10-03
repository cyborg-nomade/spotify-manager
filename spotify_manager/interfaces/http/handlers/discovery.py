"""Original discovery HTTP validation and job interactions."""

from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock

from fastapi import HTTPException
from spotipy import Spotify

from spotify_manager.interfaces.http.job_records import PlaylistJob as _BlastJob
from spotify_manager.interfaces.http.models.discovery import NewKidsChoiceRequest
from spotify_manager.interfaces.http.models.jobs import BlastJobResult
from spotify_manager.interfaces.http.validation import option_ids
from spotify_manager.routines import new_kids


@dataclass(kw_only=True)
class DiscoveryHandlers:
    """Validate and present one feature through explicit facade dependencies.

    Args:
        _ACTIVE_JOB_STATUSES: Existing overridable feature dependency.
        _active_playlist_jobs: Existing overridable feature dependency.
        _append_blast_log_locked: Existing overridable feature dependency.
        _blast_job_snapshot: Existing overridable feature dependency.
        _blast_jobs_lock: Existing overridable feature dependency.
        _configured_album_discovery_playlists: Existing overridable feature dependency.
        get_blast_job: Existing overridable feature dependency.
        start_new_kids_job: Existing overridable feature dependency.
    """

    _ACTIVE_JOB_STATUSES: set[str]
    _active_playlist_jobs: Callable[..., list[BlastJobResult]]
    _append_blast_log_locked: Callable[..., None]
    _blast_job_snapshot: Callable[..., BlastJobResult]
    _blast_jobs_lock: Lock
    _configured_album_discovery_playlists: Callable[..., tuple[str, str, str, str, str]]
    get_blast_job: Callable[..., _BlastJob]
    start_new_kids_job: Callable[..., BlastJobResult]

    def cmd_flush_new_kids(self, client: Spotify, dry_run: bool) -> BlastJobResult:
        """Start an interactive New Kids flush with reconnectable web state.

        Args:
            client: Original validated client value.
            dry_run: Original validated dry run value.

        Returns:
            Original feature response with unchanged fields and validation.
        """
        playlist_ids = self._configured_album_discovery_playlists()
        return self.start_new_kids_job(client, *playlist_ids, dry_run=dry_run)

    def cmd_active_new_kids_jobs(self) -> list[BlastJobResult]:
        """Return active New Kids jobs so the web UI can reconnect after reload.

        Returns:
            Original feature response with unchanged fields and validation.
        """
        return self._active_playlist_jobs("flush_new_kids")

    def cmd_new_kids_job(self, job_id: str) -> BlastJobResult:
        """Return current progress and any pending New Kids choice.

        Args:
            job_id: Original validated job id value.

        Returns:
            Original feature response with unchanged fields and validation.
        """
        job = self.get_blast_job(job_id, command="flush_new_kids")
        with self._blast_jobs_lock:
            return self._blast_job_snapshot(job)

    def cmd_choose_new_kids_release(
        self, job_id: str, request: NewKidsChoiceRequest
    ) -> BlastJobResult:
        """Submit one release or control choice to a waiting New Kids job.

        Args:
            job_id: Original validated job id value.
            request: Original validated request value.

        Returns:
            Original feature response with unchanged fields and validation.

        Raises:
            HTTPException: An original validation or feature error is observed.
        """
        job = self.get_blast_job(job_id, command="flush_new_kids")
        with self._blast_jobs_lock:
            pending = job.result.new_kids_pending_choice
            if job.result.status != "waiting" or pending is None:
                raise HTTPException(
                    status_code=409,
                    detail="New Kids job is not waiting for a release choice",
                )
            allowed = {
                new_kids.CHOICE_SKIP,
                new_kids.CHOICE_QUIT,
                *option_ids(pending.releases),
            }
            if request.choice not in allowed:
                raise HTTPException(
                    status_code=400, detail="release choice is not available"
                )
            job.submitted_choice = request.choice
            job.result.new_kids_pending_choice = None
            job.result.status = "running"
            job.result.detail = "Release choice submitted"
            job.choice_event.set()
            return self._blast_job_snapshot(job)

    def cmd_cancel_new_kids_job(self, job_id: str) -> BlastJobResult:
        """Request a clean stop at the next New Kids processing boundary.

        Args:
            job_id: Original validated job id value.

        Returns:
            Original feature response with unchanged fields and validation.

        Raises:
            HTTPException: An original validation or feature error is observed.
        """
        job = self.get_blast_job(job_id, command="flush_new_kids")
        with self._blast_jobs_lock:
            if job.result.status not in self._ACTIVE_JOB_STATUSES:
                raise HTTPException(
                    status_code=409, detail="New Kids job is not active"
                )
            job.result.status = "cancelling"
            job.result.new_kids_pending_choice = None
            job.result.detail = "Stopping New Kids flush"
            self._append_blast_log_locked(job, job.result.detail)
            job.cancel_event.set()
            job.choice_event.set()
            return self._blast_job_snapshot(job)
