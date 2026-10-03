"""Original daily mind radio HTTP validation and job interactions."""

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
class DailyMindRadioHandlers:
    """Validate and present one feature through explicit facade dependencies.

    Args:
        Settings: Existing overridable feature dependency.
        _active_playlist_jobs: Existing overridable feature dependency.
        _blast_job_snapshot: Existing overridable feature dependency.
        _blast_jobs_lock: Existing overridable feature dependency.
        _cancel_simple_playlist_job: Existing overridable feature dependency.
        get_blast_job: Existing overridable feature dependency.
        start_daily_mind_radio_job: Existing overridable feature dependency.
    """

    Settings: type[Settings]
    _active_playlist_jobs: Callable[..., list[BlastJobResult]]
    _blast_job_snapshot: Callable[..., BlastJobResult]
    _blast_jobs_lock: Lock
    _cancel_simple_playlist_job: Callable[..., BlastJobResult]
    get_blast_job: Callable[..., _BlastJob]
    start_daily_mind_radio_job: Callable[..., BlastJobResult]

    def cmd_daily_mind_radio(self, client: Spotify, dry_run: bool) -> BlastJobResult:
        """Start a background Daily Mind Radio anniversary update.

        Args:
            client: Original validated client value.
            dry_run: Original validated dry run value.

        Returns:
            Original feature response with unchanged fields and validation.

        Raises:
            HTTPException: An original validation or feature error is observed.
        """
        try:
            playlist_id = blast_from_past.parse_playlist_id(
                self.Settings().daily_mind_radio_playlist,
                setting_name="DAILY_MIND_RADIO_PLAYLIST",
            )
        except blast_from_past.BlastFromPastConfigError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return self.start_daily_mind_radio_job(client, playlist_id, dry_run)

    def cmd_active_daily_mind_radio_jobs(self) -> list[BlastJobResult]:
        """Return active Daily Mind Radio jobs for web reload reconnection.

        Returns:
            Original feature response with unchanged fields and validation.
        """
        return self._active_playlist_jobs("daily_mind_radio")

    def cmd_daily_mind_radio_job(self, job_id: str) -> BlastJobResult:
        """Return current progress for one Daily Mind Radio job.

        Args:
            job_id: Original validated job id value.

        Returns:
            Original feature response with unchanged fields and validation.
        """
        job = self.get_blast_job(job_id, command="daily_mind_radio")
        with self._blast_jobs_lock:
            return self._blast_job_snapshot(job)

    def cmd_cancel_daily_mind_radio_job(self, job_id: str) -> BlastJobResult:
        """Stop Daily Mind Radio at the next bounded network-operation boundary.

        Args:
            job_id: Original validated job id value.

        Returns:
            Original feature response with unchanged fields and validation.
        """
        return self._cancel_simple_playlist_job(
            job_id, command="daily_mind_radio", detail="Stopping Daily Mind Radio"
        )
