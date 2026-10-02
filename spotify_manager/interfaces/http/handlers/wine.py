"""Original wine HTTP validation and job interactions."""

from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock

from fastapi import HTTPException
from spotipy import Spotify

from spotify_manager.interfaces.http.job_records import PlaylistJob as _BlastJob
from spotify_manager.interfaces.http.models.jobs import BlastJobResult
from spotify_manager.interfaces.http.models.wine import NewWineChoiceRequest
from spotify_manager.interfaces.http.models.wine import NewWinePendingChoice
from spotify_manager.interfaces.http.validation import option_ids
from spotify_manager.routines import new_wine
from spotify_manager.settings import Settings


@dataclass(kw_only=True)
class WineHandlers:
    """Validate and present one feature through explicit facade dependencies.

    Args:
        Settings: Existing overridable feature dependency.
        _ACTIVE_JOB_STATUSES: Existing overridable feature dependency.
        _active_playlist_jobs: Existing overridable feature dependency.
        _append_blast_log_locked: Existing overridable feature dependency.
        _blast_job_snapshot: Existing overridable feature dependency.
        _blast_jobs_lock: Existing overridable feature dependency.
        get_blast_job: Existing overridable feature dependency.
        start_new_wine_job: Existing overridable feature dependency.
    """

    Settings: type[Settings]
    _ACTIVE_JOB_STATUSES: set[str]
    _active_playlist_jobs: Callable[..., list[BlastJobResult]]
    _append_blast_log_locked: Callable[..., None]
    _blast_job_snapshot: Callable[..., BlastJobResult]
    _blast_jobs_lock: Lock
    get_blast_job: Callable[..., _BlastJob]
    start_new_wine_job: Callable[..., BlastJobResult]

    def cmd_flush_new_wine(
        self,
        client: Spotify,
        dry_run: bool,
        no_discovery: bool,
        choose_album_endpoints: bool,
    ) -> BlastJobResult:
        """Start an interactive New Wine flush with reconnectable web state.

        Args:
            client: Original validated client value.
            dry_run: Original validated dry run value.
            no_discovery: Original validated no discovery value.
            choose_album_endpoints: Original validated choose album endpoints value.

            Returns:
            Original feature response with unchanged fields and validation.

            Raises:
            HTTPException: An original validation or feature error is observed.
        """
        configuration = self.Settings()
        try:
            new_wine_playlist_id = new_wine.parse_playlist_id(
                configuration.new_wine_from_old_bottles_playlist,
                ("NEW_WINE_FROM_OLD_BOTTLES_PLAYLIST"),
            )
            sauvignon_playlist_id = new_wine.parse_playlist_id(
                configuration.sauvignon_terre_neuve_playlist,
                ("SAUVIGNON_TERRE_NEUVE_PLAYLIST"),
            )
            wine_cellar_playlist_id = new_wine.parse_playlist_id(
                configuration.wine_cellar_playlist, ("WINE_CELLAR_PLAYLIST")
            )
        except new_wine.NewWineConfigError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return self.start_new_wine_job(
            client,
            new_wine_playlist_id,
            sauvignon_playlist_id,
            wine_cellar_playlist_id,
            dry_run=dry_run,
            no_discovery=no_discovery,
            choose_album_endpoints=choose_album_endpoints,
        )

    def cmd_active_new_wine_jobs(self) -> list[BlastJobResult]:
        """Return active New Wine jobs so the web UI can reconnect after reload.

        Returns:
            Original feature response with unchanged fields and validation.
        """
        return self._active_playlist_jobs("flush_new_wine")

    def cmd_new_wine_job(self, job_id: str) -> BlastJobResult:
        """Return current progress and any pending choice for one New Wine job.

        Args:
            job_id: Original validated job id value.

            Returns:
            Original feature response with unchanged fields and validation.
        """
        job = self.get_blast_job(job_id, command="flush_new_wine")
        with self._blast_jobs_lock:
            return self._blast_job_snapshot(job)

    def cmd_choose_new_wine_release(
        self, job_id: str, request: NewWineChoiceRequest
    ) -> BlastJobResult:
        """Submit one release or control choice to a waiting New Wine job.

        Args:
            job_id: Original validated job id value.
            request: Original validated request value.

            Returns:
            Original feature response with unchanged fields and validation.

            Raises:
            HTTPException: An original validation or feature error is observed.
        """
        job = self.get_blast_job(job_id, command="flush_new_wine")
        with self._blast_jobs_lock:
            pending = job.result.pending_choice
            if job.result.status != "waiting" or pending is None:
                raise HTTPException(
                    status_code=409,
                    detail=("New Wine job is not waiting for a release choice"),
                )
            self._validate_submission(pending, request)
            job.submitted_choice = request.choice
            job.result.pending_choice = None
            job.result.status = "running"
            job.result.detail = "Release choice submitted"
            job.choice_event.set()
            return self._blast_job_snapshot(job)

    def cmd_cancel_new_wine_job(self, job_id: str) -> BlastJobResult:
        """Request a clean stop at the next New Wine processing boundary.

        Args:
            job_id: Original validated job id value.

            Returns:
            Original feature response with unchanged fields and validation.

            Raises:
            HTTPException: An original validation or feature error is observed.
        """
        job = self.get_blast_job(job_id, command="flush_new_wine")
        with self._blast_jobs_lock:
            if job.result.status not in self._ACTIVE_JOB_STATUSES:
                raise HTTPException(
                    status_code=409, detail=("New Wine job is not active")
                )
            job.result.status = "cancelling"
            job.result.pending_choice = None
            job.result.detail = "Stopping New Wine flush"
            self._append_blast_log_locked(job, job.result.detail)
            job.cancel_event.set()
            job.choice_event.set()
            return self._blast_job_snapshot(job)

    def _validate_submission(
        self, pending: NewWinePendingChoice, request: NewWineChoiceRequest
    ) -> None:
        if pending.kind == "album_endpoint":
            allowed = {
                new_wine.CHOICE_CUTOFF,
                new_wine.CHOICE_CONTINUE,
                new_wine.CHOICE_SKIP,
                new_wine.CHOICE_QUIT,
            }
        else:
            allowed = {
                new_wine.CHOICE_DROP,
                new_wine.CHOICE_SKIP,
                new_wine.CHOICE_QUIT,
                *option_ids(pending.releases),
            }
            if pending.terminal_release:
                allowed.add(new_wine.CHOICE_FINISH)
        if request.choice not in allowed:
            raise HTTPException(
                status_code=400, detail=("release choice is not available")
            )
