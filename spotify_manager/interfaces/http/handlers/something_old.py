"""Original something old HTTP validation and job interactions."""

from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock

from fastapi import HTTPException
from spotipy import Spotify

from spotify_manager.interfaces.http.job_records import PlaylistJob as _BlastJob
from spotify_manager.interfaces.http.models.jobs import BlastJobResult
from spotify_manager.interfaces.http.models.something_old import (
    SomethingOldChoiceRequest,
)
from spotify_manager.interfaces.http.models.something_old import (
    SomethingOldPendingChoice,
)
from spotify_manager.interfaces.http.validation import option_ids
from spotify_manager.routines import found_art
from spotify_manager.routines import something_old
from spotify_manager.settings import Settings


@dataclass(kw_only=True)
class SomethingOldHandlers:
    """Validate and present one feature through explicit facade dependencies.

    Args:
        Settings: Existing overridable feature dependency.
        _ACTIVE_JOB_STATUSES: Existing overridable feature dependency.
        _active_playlist_jobs: Existing overridable feature dependency.
        _append_blast_log_locked: Existing overridable feature dependency.
        _blast_job_snapshot: Existing overridable feature dependency.
        _blast_jobs_lock: Existing overridable feature dependency.
        get_blast_job: Existing overridable feature dependency.
        start_something_old_job: Existing overridable feature dependency.
    """

    Settings: type[Settings]
    _ACTIVE_JOB_STATUSES: set[str]
    _active_playlist_jobs: Callable[..., list[BlastJobResult]]
    _append_blast_log_locked: Callable[..., None]
    _blast_job_snapshot: Callable[..., BlastJobResult]
    _blast_jobs_lock: Lock
    get_blast_job: Callable[..., _BlastJob]
    start_something_old_job: Callable[..., BlastJobResult]

    def cmd_something_old(self, client: Spotify, dry_run: bool) -> BlastJobResult:
        """Start an interactive Something Old selection with reconnectable state.

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
            playlist_id = something_old.parse_playlist_id(
                configuration.something_old_new_playlist
            )
            api_key, username = found_art.validate_lastfm_configuration(
                configuration.lastfm_api_key, configuration.lastfm_username
            )
        except (
            something_old.SomethingOldConfigError,
            found_art.FoundArtConfigError,
        ) as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return self.start_something_old_job(
            client, playlist_id, api_key, username, dry_run=dry_run
        )

    def cmd_active_something_old_jobs(self) -> list[BlastJobResult]:
        """Return active Something Old jobs for page-reload reconnection.

        Returns:
            Original feature response with unchanged fields and validation.
        """
        return self._active_playlist_jobs("something_old")

    def cmd_something_old_job(self, job_id: str) -> BlastJobResult:
        """Return current Something Old progress and any pending choice.

        Args:
            job_id: Original validated job id value.

            Returns:
            Original feature response with unchanged fields and validation.
        """
        job = self.get_blast_job(job_id, command="something_old")
        with self._blast_jobs_lock:
            return self._blast_job_snapshot(job)

    def cmd_choose_something_old(
        self, job_id: str, request: SomethingOldChoiceRequest
    ) -> BlastJobResult:
        """Submit an exact artist, source mode, album/EP, or quit choice.

        Args:
            job_id: Original validated job id value.
            request: Original validated request value.

            Returns:
            Original feature response with unchanged fields and validation.

            Raises:
            HTTPException: An original validation or feature error is observed.
        """
        job = self.get_blast_job(job_id, command="something_old")
        with self._blast_jobs_lock:
            pending = job.result.something_old_pending_choice
            if job.result.status != "waiting" or pending is None:
                raise HTTPException(
                    status_code=409,
                    detail=("Something Old job is not waiting for a choice"),
                )
            self._validate_submission(pending, request)
            job.submitted_choice = request.choice
            job.result.something_old_pending_choice = None
            job.result.status = "running"
            job.result.detail = "Something Old choice submitted"
            job.choice_event.set()
            return self._blast_job_snapshot(job)

    def cmd_cancel_something_old_job(self, job_id: str) -> BlastJobResult:
        """Request a clean stop at the next Something Old boundary.

        Args:
            job_id: Original validated job id value.

            Returns:
            Original feature response with unchanged fields and validation.

            Raises:
            HTTPException: An original validation or feature error is observed.
        """
        job = self.get_blast_job(job_id, command="something_old")
        with self._blast_jobs_lock:
            if job.result.status not in self._ACTIVE_JOB_STATUSES:
                raise HTTPException(
                    status_code=409, detail=("Something Old job is not active")
                )
            job.result.status = "cancelling"
            job.result.something_old_pending_choice = None
            job.result.detail = "Stopping Something Old"
            self._append_blast_log_locked(job, job.result.detail)
            job.cancel_event.set()
            job.choice_event.set()
            return self._blast_job_snapshot(job)

    def _validate_submission(
        self, pending: SomethingOldPendingChoice, request: SomethingOldChoiceRequest
    ) -> None:
        if pending.kind == "artist":
            allowed = {"quit", *option_ids(pending.artist_candidates)}
        elif pending.kind == "mode":
            allowed = {"lastfm_top_tracks", "spotify_top_tracks", "album", "quit"}
        else:
            allowed = {"quit", *option_ids(pending.releases)}
        if request.choice not in allowed:
            raise HTTPException(
                status_code=400, detail=("Something Old choice is not available")
            )
