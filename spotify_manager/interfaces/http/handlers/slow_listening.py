"""Original slow listening HTTP validation and job interactions."""

from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock

from fastapi import HTTPException
from spotipy import Spotify

from spotify_manager.interfaces.http.job_records import PlaylistJob as _BlastJob
from spotify_manager.interfaces.http.models.jobs import BlastJobResult
from spotify_manager.interfaces.http.models.slow_listening import (
    SlowListeningChoiceRequest,
)
from spotify_manager.interfaces.http.models.slow_listening import (
    SlowListeningPendingChoice,
)
from spotify_manager.interfaces.http.validation import option_ids
from spotify_manager.routines import slow_listening
from spotify_manager.settings import Settings


@dataclass(kw_only=True)
class SlowListeningHandlers:
    """Validate and present one feature through explicit facade dependencies.

    Args:
        Settings: Existing overridable feature dependency.
        _ACTIVE_JOB_STATUSES: Existing overridable feature dependency.
        _active_playlist_jobs: Existing overridable feature dependency.
        _append_blast_log_locked: Existing overridable feature dependency.
        _blast_job_snapshot: Existing overridable feature dependency.
        _blast_jobs_lock: Existing overridable feature dependency.
        get_blast_job: Existing overridable feature dependency.
        start_slow_listening_job: Existing overridable feature dependency.
    """

    Settings: type[Settings]
    _ACTIVE_JOB_STATUSES: set[str]
    _active_playlist_jobs: Callable[..., list[BlastJobResult]]
    _append_blast_log_locked: Callable[..., None]
    _blast_job_snapshot: Callable[..., BlastJobResult]
    _blast_jobs_lock: Lock
    get_blast_job: Callable[..., _BlastJob]
    start_slow_listening_job: Callable[..., BlastJobResult]

    def cmd_flush_slow_listening(
        self, client: Spotify, dry_run: bool
    ) -> BlastJobResult:
        """Start an interactive Slow Listening flush with reconnectable state.

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
            playlist_id = slow_listening.parse_playlist_id(
                configuration.slow_listening_playlist
            )
        except slow_listening.SlowListeningConfigError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return self.start_slow_listening_job(client, playlist_id, dry_run=dry_run)

    def cmd_active_slow_listening_jobs(self) -> list[BlastJobResult]:
        """Return active Slow Listening jobs for page-reload reconnection.

        Returns:
            Original feature response with unchanged fields and validation.
        """
        return self._active_playlist_jobs("flush_slow_listening")

    def cmd_slow_listening_job(self, job_id: str) -> BlastJobResult:
        """Return current progress and the pending Slow Listening choice.

        Args:
            job_id: Original validated job id value.

        Returns:
            Original feature response with unchanged fields and validation.
        """
        job = self.get_blast_job(job_id, command="flush_slow_listening")
        with self._blast_jobs_lock:
            return self._blast_job_snapshot(job)

    def cmd_choose_slow_listening_track(
        self, job_id: str, request: SlowListeningChoiceRequest
    ) -> BlastJobResult:
        """Submit a candidate, release order, or completion acknowledgement.

        Args:
            job_id: Original validated job id value.
            request: Original validated request value.

        Returns:
            Original feature response with unchanged fields and validation.

        Raises:
            HTTPException: An original validation or feature error is observed.
        """
        job = self.get_blast_job(job_id, command="flush_slow_listening")
        with self._blast_jobs_lock:
            pending = job.result.slow_listening_pending_choice
            if job.result.status != "waiting" or pending is None:
                raise HTTPException(
                    status_code=409,
                    detail="Slow Listening job is not waiting for a choice",
                )
            submitted_order = self._validate_submission(pending, request)
            job.submitted_choice = request.choice
            job.submitted_order = submitted_order
            job.result.slow_listening_pending_choice = None
            job.result.status = "running"
            job.result.detail = "Slow Listening choice submitted"
            job.choice_event.set()
            return self._blast_job_snapshot(job)

    def cmd_cancel_slow_listening_job(self, job_id: str) -> BlastJobResult:
        """Request a clean stop at the next Slow Listening boundary.

        Args:
            job_id: Original validated job id value.

        Returns:
            Original feature response with unchanged fields and validation.

        Raises:
            HTTPException: An original validation or feature error is observed.
        """
        job = self.get_blast_job(job_id, command="flush_slow_listening")
        with self._blast_jobs_lock:
            if job.result.status not in self._ACTIVE_JOB_STATUSES:
                raise HTTPException(
                    status_code=409, detail="Slow Listening job is not active"
                )
            job.result.status = "cancelling"
            job.result.slow_listening_pending_choice = None
            job.result.detail = "Stopping Slow Listening flush"
            self._append_blast_log_locked(job, job.result.detail)
            job.cancel_event.set()
            job.choice_event.set()
            return self._blast_job_snapshot(job)

    def _validate_submission(
        self, pending: SlowListeningPendingChoice, request: SlowListeningChoiceRequest
    ) -> tuple[str, ...] | None:
        submitted_order: tuple[str, ...] | None = None
        if pending.kind == "track":
            allowed = {
                slow_listening.CHOICE_ADVANCE,
                slow_listening.CHOICE_SKIP,
                slow_listening.CHOICE_QUIT,
            }
            if request.choice not in allowed or request.order:
                raise HTTPException(
                    status_code=400, detail="track choice is not available"
                )
        elif pending.kind == "release_order":
            expected_ids = set(option_ids(pending.releases))
            submitted_order = tuple(request.order)
            if (
                request.choice != "order"
                or len(submitted_order) != len(expected_ids)
                or set(submitted_order) != expected_ids
            ):
                raise HTTPException(
                    status_code=400,
                    detail="release order must include every option exactly once",
                )
        elif request.choice != "continue" or request.order:
            raise HTTPException(
                status_code=400, detail="completion choice is not available"
            )
        return submitted_order
