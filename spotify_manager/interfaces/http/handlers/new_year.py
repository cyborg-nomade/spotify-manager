"""Original new year HTTP validation and job interactions."""

from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock
from threading import Thread
from uuid import UUID

from spotipy import Spotify

from spotify_manager.interfaces.http.job_records import PlaylistJob as _BlastJob
from spotify_manager.interfaces.http.models.jobs import BlastJobResult


@dataclass(kw_only=True)
class NewYearHandlers:
    """Validate and present one feature through explicit facade dependencies.

    Args:
        Thread: Existing overridable feature dependency.
        _active_playlist_jobs: Existing overridable feature dependency.
        _blast_job_snapshot: Existing overridable feature dependency.
        _blast_jobs: Existing overridable feature dependency.
        _blast_jobs_lock: Existing overridable feature dependency.
        _cancel_simple_playlist_job: Existing overridable feature dependency.
        _require_playlist_slot: Existing overridable feature dependency.
        _run_new_year_job: Existing overridable feature dependency.
        get_blast_job: Existing overridable feature dependency.
        uuid4: Existing overridable feature dependency.
    """

    Thread: type[Thread]
    _active_playlist_jobs: Callable[..., list[BlastJobResult]]
    _blast_job_snapshot: Callable[..., BlastJobResult]
    _blast_jobs: dict[str, _BlastJob]
    _blast_jobs_lock: Lock
    _cancel_simple_playlist_job: Callable[..., BlastJobResult]
    _require_playlist_slot: Callable[..., None]
    _run_new_year_job: Callable[..., None]
    get_blast_job: Callable[..., _BlastJob]
    uuid4: Callable[[], UUID]

    def cmd_new_year(
        self, client: Spotify, dry_run: bool, year: int | None
    ) -> BlastJobResult:
        """Start all New Year's Routines for the previous completed calendar year.

        Args:
            client: Original validated client value.
            dry_run: Original validated dry run value.
            year: Original validated year value.

            Returns:
            Original feature response with unchanged fields and validation.
        """
        with self._blast_jobs_lock:
            self._require_playlist_slot(
                "another playlist or history routine is running"
            )
            job_id = self.uuid4().hex
            job = _BlastJob(
                result=BlastJobResult(
                    job_id=job_id, command=("new_year"), dry_run=dry_run
                )
            )
            self._blast_jobs[job_id] = job
            snapshot = self._blast_job_snapshot(job)
        self.Thread(
            target=self._run_new_year_job,
            args=(job_id, client, year, dry_run),
            name=(f"new-year-{job_id[:8]}"),
            daemon=True,
        ).start()
        return snapshot

    def cmd_active_new_year_jobs(self) -> list[BlastJobResult]:
        """Reconnect to an active annual workflow after browser reload.

        Returns:
            Original feature response with unchanged fields and validation.
        """
        return self._active_playlist_jobs("new_year")

    def cmd_new_year_job(self, job_id: str) -> BlastJobResult:
        """Return annual progress, rankings, and logs.

        Args:
            job_id: Original validated job id value.

            Returns:
            Original feature response with unchanged fields and validation.
        """
        job = self.get_blast_job(job_id, command="new_year")
        with self._blast_jobs_lock:
            return self._blast_job_snapshot(job)

    def cmd_cancel_new_year_job(self, job_id: str) -> BlastJobResult:
        """Cancel at the next boundary, retaining completed annual steps.

        Args:
            job_id: Original validated job id value.

            Returns:
            Original feature response with unchanged fields and validation.
        """
        return self._cancel_simple_playlist_job(
            job_id, command=("new_year"), detail=("Stopping New Year's Routines")
        )
