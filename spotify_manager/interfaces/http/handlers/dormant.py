"""Original dormant HTTP validation and job interactions."""

from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock

from fastapi import HTTPException
from spotipy import Spotify

from spotify_manager.interfaces.http.job_records import PlaylistJob as _BlastJob
from spotify_manager.interfaces.http.models.jobs import BlastJobResult
from spotify_manager.routines import blast_from_past
from spotify_manager.settings import Settings


@dataclass(kw_only=True)
class DormantHandlers:
    """Validate and present one feature through explicit facade dependencies.

    Args:
        Settings: Existing overridable feature dependency.
        _active_playlist_jobs: Existing overridable feature dependency.
        _blast_job_snapshot: Existing overridable feature dependency.
        _blast_jobs_lock: Existing overridable feature dependency.
        _cancel_simple_playlist_job: Existing overridable feature dependency.
        get_blast_job: Existing overridable feature dependency.
        start_blast_artist_job: Existing overridable feature dependency.
    """

    Settings: type[Settings]
    _active_playlist_jobs: Callable[..., list[BlastJobResult]]
    _blast_job_snapshot: Callable[..., BlastJobResult]
    _blast_jobs_lock: Lock
    _cancel_simple_playlist_job: Callable[..., BlastJobResult]
    get_blast_job: Callable[..., _BlastJob]
    start_blast_artist_job: Callable[..., BlastJobResult]

    def cmd_blast_from_the_past_artists(
        self, client: Spotify, count: int, dry_run: bool
    ) -> BlastJobResult:
        """Start an alphabetic dormant-artist recovery update.

        Args:
            client: Original validated client value.
            count: Original validated count value.
            dry_run: Original validated dry run value.

        Returns:
            Original feature response with unchanged fields and validation.

        Raises:
            HTTPException: An original validation or feature error is observed.
        """
        try:
            playlist_id = blast_from_past.parse_playlist_id(
                self.Settings().blast_from_the_past_playlist
            )
        except blast_from_past.BlastFromPastConfigError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return self.start_blast_artist_job(client, playlist_id, count, dry_run)

    def cmd_active_blast_artist_jobs(self) -> list[BlastJobResult]:
        """Return the active dormant-artist job for browser reconnection.

        Returns:
            Original feature response with unchanged fields and validation.
        """
        return self._active_playlist_jobs("blast_from_the_past_artists")

    def cmd_blast_artist_job(self, job_id: str) -> BlastJobResult:
        """Return current progress for one dormant-artist job.

        Args:
            job_id: Original validated job id value.

        Returns:
            Original feature response with unchanged fields and validation.
        """
        job = self.get_blast_job(job_id, command="blast_from_the_past_artists")
        with self._blast_jobs_lock:
            return self._blast_job_snapshot(job)

    def cmd_cancel_blast_artist_job(self, job_id: str) -> BlastJobResult:
        """Cancel dormant-artist recovery at the next safe boundary.

        Args:
            job_id: Original validated job id value.

        Returns:
            Original feature response with unchanged fields and validation.
        """
        return self._cancel_simple_playlist_job(
            job_id,
            command="blast_from_the_past_artists",
            detail="Stopping dormant-artist recovery",
        )
