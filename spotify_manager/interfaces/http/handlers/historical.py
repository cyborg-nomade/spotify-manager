"""Original historical HTTP validation and job interactions."""

from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock

from fastapi import HTTPException
from spotipy import Spotify

from spotify_manager.interfaces.http.job_records import PlaylistJob as _BlastJob
from spotify_manager.interfaces.http.models.jobs import BlastJobResult
from spotify_manager.interfaces.operations import blast_from_past as blast_from_past
from spotify_manager.settings import Settings


@dataclass(kw_only=True)
class HistoricalHandlers:
    """Validate and present one feature through explicit facade dependencies.

    Args:
        Settings: Existing overridable feature dependency.
        _active_playlist_jobs: Existing overridable feature dependency.
        _blast_job_snapshot: Existing overridable feature dependency.
        _blast_jobs_lock: Existing overridable feature dependency.
        _cancel_simple_playlist_job: Existing overridable feature dependency.
        get_blast_job: Existing overridable feature dependency.
        start_blast_job: Existing overridable feature dependency.
    """

    Settings: type[Settings]
    _active_playlist_jobs: Callable[..., list[BlastJobResult]]
    _blast_job_snapshot: Callable[..., BlastJobResult]
    _blast_jobs_lock: Lock
    _cancel_simple_playlist_job: Callable[..., BlastJobResult]
    get_blast_job: Callable[..., _BlastJob]
    start_blast_job: Callable[..., BlastJobResult]

    def cmd_blast_from_the_past(
        self,
        client: Spotify,
        count: int | None,
        max_playlist_length: int | None,
        dry_run: bool,
    ) -> BlastJobResult:
        """Start a background Friday-routine playlist update.

        Args:
            client: Original validated client value.
            count: Original validated count value.
            max_playlist_length: Original validated max playlist length value.
            dry_run: Original validated dry run value.

        Returns:
            Original feature response with unchanged fields and validation.

        Raises:
            HTTPException: An original validation or feature error is observed.
        """
        if count is not None and max_playlist_length is not None:
            raise HTTPException(
                status_code=400,
                detail="use either count or max_playlist_length, not both",
            )
        effective_count = 10 if count is None and max_playlist_length is None else count
        try:
            playlist_id = blast_from_past.parse_playlist_id(
                self.Settings().blast_from_the_past_playlist
            )
        except blast_from_past.BlastFromPastConfigError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return self.start_blast_job(
            client, playlist_id, effective_count, max_playlist_length, dry_run
        )

    def cmd_active_blast_jobs(self) -> list[BlastJobResult]:
        """Return active playlist jobs so the web UI can reconnect after reload.

        Returns:
            Original feature response with unchanged fields and validation.
        """
        return self._active_playlist_jobs("blast_from_the_past")

    def cmd_blast_job(self, job_id: str) -> BlastJobResult:
        """Return current progress for one playlist job.

        Args:
            job_id: Original validated job id value.

        Returns:
            Original feature response with unchanged fields and validation.
        """
        job = self.get_blast_job(job_id, command="blast_from_the_past")
        with self._blast_jobs_lock:
            return self._blast_job_snapshot(job)

    def cmd_cancel_blast_job(self, job_id: str) -> BlastJobResult:
        """Stop a Blast job at the next bounded network-operation boundary.

        Args:
            job_id: Original validated job id value.

        Returns:
            Original feature response with unchanged fields and validation.
        """
        return self._cancel_simple_playlist_job(
            job_id,
            command="blast_from_the_past",
            detail="Stopping A blast from the past",
        )
