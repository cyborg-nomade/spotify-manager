"""Original queue flush HTTP validation and job interactions."""

from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock

from spotipy import Spotify

from spotify_manager.interfaces.http.job_records import PlaylistJob as _BlastJob
from spotify_manager.interfaces.http.models.jobs import BlastJobResult
from spotify_manager.routines import the_queue


@dataclass(kw_only=True)
class QueueFlushHandlers:
    """Validate and present one feature through explicit facade dependencies.

    Args:
        _active_playlist_jobs: Existing overridable feature dependency.
        _blast_job_snapshot: Existing overridable feature dependency.
        _blast_jobs_lock: Existing overridable feature dependency.
        _cancel_queue_job: Existing overridable feature dependency.
        _configured_queue_playlists: Existing overridable feature dependency.
        get_blast_job: Existing overridable feature dependency.
        start_queue_flush_job: Existing overridable feature dependency.
    """

    _active_playlist_jobs: Callable[..., list[BlastJobResult]]
    _blast_job_snapshot: Callable[..., BlastJobResult]
    _blast_jobs_lock: Lock
    _cancel_queue_job: Callable[..., BlastJobResult]
    _configured_queue_playlists: Callable[..., the_queue.QueuePlaylists]
    get_blast_job: Callable[..., _BlastJob]
    start_queue_flush_job: Callable[..., BlastJobResult]

    def cmd_flush_queue(self, client: Spotify, dry_run: bool) -> BlastJobResult:
        """Start a reconnectable flush of the first ten Queue artists.

        Args:
            client: Original validated client value.
            dry_run: Original validated dry run value.

            Returns:
            Original feature response with unchanged fields and validation.
        """
        return self.start_queue_flush_job(
            client, self._configured_queue_playlists(), dry_run=dry_run
        )

    def cmd_active_queue_flush_jobs(self) -> list[BlastJobResult]:
        """Return active Queue flush jobs for page reload reconnection.

        Returns:
            Original feature response with unchanged fields and validation.
        """
        return self._active_playlist_jobs("flush_queue")

    def cmd_queue_flush_job(self, job_id: str) -> BlastJobResult:
        """Return current Queue flush progress and result details.

        Args:
            job_id: Original validated job id value.

            Returns:
            Original feature response with unchanged fields and validation.
        """
        job = self.get_blast_job(job_id, command="flush_queue")
        with self._blast_jobs_lock:
            return self._blast_job_snapshot(job)

    def cmd_cancel_queue_flush_job(self, job_id: str) -> BlastJobResult:
        """Stop a Queue flush while preserving its durable checkpoint.

        Args:
            job_id: Original validated job id value.

            Returns:
            Original feature response with unchanged fields and validation.
        """
        return self._cancel_queue_job(job_id, "flush_queue", "Queue flush")
