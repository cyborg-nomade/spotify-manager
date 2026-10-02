"""Original sauvignon HTTP validation and job interactions."""

from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock

from fastapi import HTTPException
from spotipy import Spotify

from spotify_manager.interfaces.http.job_records import PlaylistJob as _BlastJob
from spotify_manager.interfaces.http.models.jobs import BlastJobResult
from spotify_manager.interfaces.http.models.recommendations import (
    SauvignonChoiceRequest,
)
from spotify_manager.interfaces.http.validation import option_ids
from spotify_manager.routines import found_art
from spotify_manager.routines import sauvignon
from spotify_manager.settings import Settings


@dataclass(kw_only=True)
class SauvignonHandlers:
    """Validate and present one feature through explicit facade dependencies.

    Args:
        Settings: Existing overridable feature dependency.
        _ACTIVE_JOB_STATUSES: Existing overridable feature dependency.
        _active_playlist_jobs: Existing overridable feature dependency.
        _append_blast_log_locked: Existing overridable feature dependency.
        _blast_job_snapshot: Existing overridable feature dependency.
        _blast_jobs_lock: Existing overridable feature dependency.
        get_blast_job: Existing overridable feature dependency.
        start_sauvignon_job: Existing overridable feature dependency.
    """

    Settings: type[Settings]
    _ACTIVE_JOB_STATUSES: set[str]
    _active_playlist_jobs: Callable[..., list[BlastJobResult]]
    _append_blast_log_locked: Callable[..., None]
    _blast_job_snapshot: Callable[..., BlastJobResult]
    _blast_jobs_lock: Lock
    get_blast_job: Callable[..., _BlastJob]
    start_sauvignon_job: Callable[..., BlastJobResult]

    def cmd_fill_sauvignon_from_lastfm(
        self,
        client: Spotify,
        count: int | None,
        max_playlist_length: int | None,
        seed_count: int,
        dry_run: bool,
    ) -> BlastJobResult:
        """Start reconnectable Last.fm album discovery for Sauvignon.

        Args:
            client: Original validated client value.
            count: Original validated count value.
            max_playlist_length: Original validated max playlist length value.
            seed_count: Original validated seed count value.
            dry_run: Original validated dry run value.

            Returns:
            Original feature response with unchanged fields and validation.

            Raises:
            HTTPException: An original validation or feature error is observed.
        """
        if count is not None and max_playlist_length is not None:
            raise HTTPException(
                status_code=400,
                detail=("use either count or maximum playlist length, not both"),
            )
        configuration = self.Settings()
        try:
            playlist_id = sauvignon.parse_playlist_id(
                configuration.sauvignon_terre_neuve_playlist
            )
            api_key, username = found_art.validate_lastfm_configuration(
                configuration.lastfm_api_key, configuration.lastfm_username
            )
        except (sauvignon.SauvignonConfigError, found_art.FoundArtConfigError) as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        effective_maximum = (
            sauvignon.DEFAULT_MAX_PLAYLIST_LENGTH
            if count is None and max_playlist_length is None
            else max_playlist_length
        )
        return self.start_sauvignon_job(
            client,
            playlist_id,
            api_key,
            username,
            count=count,
            max_playlist_length=effective_maximum,
            seed_count=seed_count,
            dry_run=dry_run,
        )

    def cmd_active_sauvignon_jobs(self) -> list[BlastJobResult]:
        """Return active Sauvignon jobs so the UI can reconnect after reload.

        Returns:
            Original feature response with unchanged fields and validation.
        """
        return self._active_playlist_jobs("fill_sauvignon_from_lastfm")

    def cmd_sauvignon_job(self, job_id: str) -> BlastJobResult:
        """Return Sauvignon progress and any pending album-edition choice.

        Args:
            job_id: Original validated job id value.

            Returns:
            Original feature response with unchanged fields and validation.
        """
        job = self.get_blast_job(job_id, command="fill_sauvignon_from_lastfm")
        with self._blast_jobs_lock:
            return self._blast_job_snapshot(job)

    def cmd_choose_sauvignon_album(
        self, job_id: str, request: SauvignonChoiceRequest
    ) -> BlastJobResult:
        """Submit one ambiguous Spotify album edition, skip, or quit choice.

        Args:
            job_id: Original validated job id value.
            request: Original validated request value.

            Returns:
            Original feature response with unchanged fields and validation.

            Raises:
            HTTPException: An original validation or feature error is observed.
        """
        job = self.get_blast_job(job_id, command="fill_sauvignon_from_lastfm")
        with self._blast_jobs_lock:
            pending = job.result.sauvignon_pending_choice
            if job.result.status != "waiting" or pending is None:
                raise HTTPException(
                    status_code=409,
                    detail=("Sauvignon discovery is not waiting for an album choice"),
                )
            allowed = {
                sauvignon.CHOICE_SKIP,
                sauvignon.CHOICE_QUIT,
                *option_ids(pending.options),
            }
            if request.choice not in allowed:
                raise HTTPException(
                    status_code=400, detail=("album choice is not available")
                )
            job.submitted_choice = request.choice
            job.result.sauvignon_pending_choice = None
            job.result.status = "running"
            job.result.detail = "Sauvignon album choice submitted"
            job.choice_event.set()
            return self._blast_job_snapshot(job)

    def cmd_cancel_sauvignon_job(self, job_id: str) -> BlastJobResult:
        """Stop Sauvignon discovery at its next safe boundary.

        Args:
            job_id: Original validated job id value.

            Returns:
            Original feature response with unchanged fields and validation.

            Raises:
            HTTPException: An original validation or feature error is observed.
        """
        job = self.get_blast_job(job_id, command="fill_sauvignon_from_lastfm")
        with self._blast_jobs_lock:
            if job.result.status not in self._ACTIVE_JOB_STATUSES:
                raise HTTPException(
                    status_code=409, detail=("Sauvignon discovery job is not active")
                )
            job.result.status = "cancelling"
            job.result.sauvignon_pending_choice = None
            job.result.detail = "Stopping Sauvignon album discovery"
            self._append_blast_log_locked(job, job.result.detail)
            job.cancel_event.set()
            job.choice_event.set()
            return self._blast_job_snapshot(job)
