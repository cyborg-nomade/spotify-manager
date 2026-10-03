"""Original found art HTTP validation and job interactions."""

from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock

from fastapi import HTTPException
from spotipy import Spotify

from spotify_manager.interfaces.http.job_records import PlaylistJob as _BlastJob
from spotify_manager.interfaces.http.models.jobs import BlastJobResult
from spotify_manager.routines import found_art
from spotify_manager.settings import Settings


@dataclass(kw_only=True)
class FoundArtHandlers:
    """Validate and present one feature through explicit facade dependencies.

    Args:
        Settings: Existing overridable feature dependency.
        _active_playlist_jobs: Existing overridable feature dependency.
        _blast_job_snapshot: Existing overridable feature dependency.
        _blast_jobs_lock: Existing overridable feature dependency.
        get_blast_job: Existing overridable feature dependency.
        start_found_art_job: Existing overridable feature dependency.
    """

    Settings: type[Settings]
    _active_playlist_jobs: Callable[..., list[BlastJobResult]]
    _blast_job_snapshot: Callable[..., BlastJobResult]
    _blast_jobs_lock: Lock
    get_blast_job: Callable[..., _BlastJob]
    start_found_art_job: Callable[..., BlastJobResult]

    def cmd_found_art(self, client: Spotify, count: int) -> BlastJobResult:
        """Start a background Found Art recommendation update.

        Args:
            client: Original validated client value.
            count: Original validated count value.

        Returns:
            Original feature response with unchanged fields and validation.

        Raises:
            HTTPException: An original validation or feature error is observed.
        """
        configuration = self.Settings()
        try:
            playlist_id = found_art.parse_found_art_playlist_id(
                configuration.found_art_playlist
            )
            api_key, username = found_art.validate_lastfm_configuration(
                configuration.lastfm_api_key, configuration.lastfm_username
            )
        except found_art.FoundArtConfigError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return self.start_found_art_job(client, playlist_id, api_key, username, count)

    def cmd_active_found_art_jobs(self) -> list[BlastJobResult]:
        """Return active Found Art jobs for web reload reconnection.

        Returns:
            Original feature response with unchanged fields and validation.
        """
        return self._active_playlist_jobs("found_art")

    def cmd_found_art_job(self, job_id: str) -> BlastJobResult:
        """Return current progress for one Found Art job.

        Args:
            job_id: Original validated job id value.

        Returns:
            Original feature response with unchanged fields and validation.
        """
        job = self.get_blast_job(job_id, command="found_art")
        with self._blast_jobs_lock:
            return self._blast_job_snapshot(job)
