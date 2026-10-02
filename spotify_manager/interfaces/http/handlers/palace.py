"""Original palace HTTP validation and job interactions."""

from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock

from fastapi import HTTPException
from spotipy import Spotify

from spotify_manager.interfaces.http.job_records import PlaylistJob as _BlastJob
from spotify_manager.interfaces.http.models.jobs import BlastJobResult
from spotify_manager.routines import palace_of_memory
from spotify_manager.settings import Settings


@dataclass(kw_only=True)
class PalaceHandlers:
    """Validate and present one feature through explicit facade dependencies.

    Args:
        Settings: Existing overridable feature dependency.
        _ACTIVE_JOB_STATUSES: Existing overridable feature dependency.
        _active_playlist_jobs: Existing overridable feature dependency.
        _append_blast_log_locked: Existing overridable feature dependency.
        _blast_job_snapshot: Existing overridable feature dependency.
        _blast_jobs_lock: Existing overridable feature dependency.
        get_blast_job: Existing overridable feature dependency.
        start_palace_of_memory_job: Existing overridable feature dependency.
    """

    Settings: type[Settings]
    _ACTIVE_JOB_STATUSES: set[str]
    _active_playlist_jobs: Callable[..., list[BlastJobResult]]
    _append_blast_log_locked: Callable[..., None]
    _blast_job_snapshot: Callable[..., BlastJobResult]
    _blast_jobs_lock: Lock
    get_blast_job: Callable[..., _BlastJob]
    start_palace_of_memory_job: Callable[..., BlastJobResult]

    def cmd_fill_palace_of_memory(
        self,
        client: Spotify,
        dry_run: bool,
        alphabetical_start: str | None,
        set_alphabetical_cursor: int | None,
    ) -> BlastJobResult:
        """Start a reconnectable Palace fill or cursor-only adjustment.

        Args:
            client: Original validated client value.
            dry_run: Original validated dry run value.
            alphabetical_start: Original validated alphabetical start value.
            set_alphabetical_cursor: Original validated set alphabetical cursor value.

            Returns:
            Original feature response with unchanged fields and validation.

            Raises:
            HTTPException: An original validation or feature error is observed.
        """
        cleaned_start = alphabetical_start.strip() if alphabetical_start else None
        if set_alphabetical_cursor is not None and dry_run:
            raise HTTPException(
                status_code=400,
                detail=(
                    "set_alphabetical_cursor persists immediately "
                    "and cannot use dry_run"
                ),
            )
        if set_alphabetical_cursor is not None and cleaned_start is not None:
            raise HTTPException(
                status_code=400,
                detail=(
                    "use either set_alphabetical_cursor or alphabetical_start, not both"
                ),
            )
        playlist_id = None
        if set_alphabetical_cursor is None:
            configuration = self.Settings()
            try:
                playlist_id = palace_of_memory.parse_playlist_id(
                    configuration.palace_of_memory_playlist
                )
            except palace_of_memory.PalaceOfMemoryConfigError as exc:
                raise HTTPException(status_code=500, detail=str(exc)) from exc
        return self.start_palace_of_memory_job(
            client,
            playlist_id,
            dry_run=dry_run,
            alphabetical_start=cleaned_start,
            cursor_position=set_alphabetical_cursor,
        )

    def cmd_active_palace_of_memory_jobs(self) -> list[BlastJobResult]:
        """Return active Palace jobs after a page reload.

        Returns:
            Original feature response with unchanged fields and validation.
        """
        return self._active_playlist_jobs("fill_palace_of_memory")

    def cmd_palace_of_memory_job(self, job_id: str) -> BlastJobResult:
        """Return current Palace progress, results, and logs.

        Args:
            job_id: Original validated job id value.

            Returns:
            Original feature response with unchanged fields and validation.
        """
        job = self.get_blast_job(job_id, command="fill_palace_of_memory")
        with self._blast_jobs_lock:
            return self._blast_job_snapshot(job)

    def cmd_cancel_palace_of_memory_job(self, job_id: str) -> BlastJobResult:
        """Request a clean Palace stop at the next API or retry boundary.

        Args:
            job_id: Original validated job id value.

            Returns:
            Original feature response with unchanged fields and validation.

            Raises:
            HTTPException: An original validation or feature error is observed.
        """
        job = self.get_blast_job(job_id, command="fill_palace_of_memory")
        with self._blast_jobs_lock:
            if job.result.status not in self._ACTIVE_JOB_STATUSES:
                raise HTTPException(
                    status_code=409, detail=("Palace of Memory job is not active")
                )
            job.result.status = "cancelling"
            job.result.detail = "Stopping Palace of Memory"
            self._append_blast_log_locked(job, job.result.detail)
            job.cancel_event.set()
            return self._blast_job_snapshot(job)
