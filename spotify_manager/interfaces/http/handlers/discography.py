"""Original discography HTTP validation and job interactions."""

from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock

from fastapi import HTTPException
from spotipy import Spotify

from spotify_manager.interfaces.http.job_records import PlaylistJob as _BlastJob
from spotify_manager.interfaces.http.models.discography import DiscographyChoiceRequest
from spotify_manager.interfaces.http.models.discography import DiscographyPendingChoice
from spotify_manager.interfaces.http.models.jobs import BlastJobResult
from spotify_manager.interfaces.http.validation import option_ids
from spotify_manager.routines import discography
from spotify_manager.settings import Settings


@dataclass(kw_only=True)
class DiscographyHandlers:
    """Validate and present one feature through explicit facade dependencies.

    Args:
        Settings: Existing overridable feature dependency.
        _ACTIVE_JOB_STATUSES: Existing overridable feature dependency.
        _active_playlist_jobs: Existing overridable feature dependency.
        _append_blast_log_locked: Existing overridable feature dependency.
        _blast_job_snapshot: Existing overridable feature dependency.
        _blast_jobs_lock: Existing overridable feature dependency.
        get_blast_job: Existing overridable feature dependency.
        start_discography_job: Existing overridable feature dependency.
    """

    Settings: type[Settings]
    _ACTIVE_JOB_STATUSES: set[str]
    _active_playlist_jobs: Callable[..., list[BlastJobResult]]
    _append_blast_log_locked: Callable[..., None]
    _blast_job_snapshot: Callable[..., BlastJobResult]
    _blast_jobs_lock: Lock
    get_blast_job: Callable[..., _BlastJob]
    start_discography_job: Callable[..., BlastJobResult]

    def cmd_plan_discographies(self, client: Spotify, dry_run: bool) -> BlastJobResult:
        """Start a reload-safe interactive discography planning job.

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
            playlist_ids = discography.parse_playlist_ids(
                configuration.discography_newfoundland_playlist,
                configuration.discography_memory_lane_playlist,
                configuration.discography_requeue_playlist,
            )
            queue_3_playlist_id = discography.parse_playlist_id(
                configuration.the_queue_3_playlist, ("THE_QUEUE_3_PLAYLIST")
            )
        except discography.DiscographyConfigError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return self.start_discography_job(
            client, playlist_ids, queue_3_playlist_id, dry_run=dry_run
        )

    def cmd_active_discography_jobs(self) -> list[BlastJobResult]:
        """Return active discography jobs for page-reload reconnection.

        Returns:
            Original feature response with unchanged fields and validation.
        """
        return self._active_playlist_jobs("plan_discographies")

    def cmd_discography_job(self, job_id: str) -> BlastJobResult:
        """Return discography progress and its current interaction.

        Args:
            job_id: Original validated job id value.

            Returns:
            Original feature response with unchanged fields and validation.
        """
        job = self.get_blast_job(job_id, command="plan_discographies")
        with self._blast_jobs_lock:
            return self._blast_job_snapshot(job)

    def cmd_choose_discography(
        self, job_id: str, request: DiscographyChoiceRequest
    ) -> BlastJobResult:
        """Submit a release checklist or final marker-removal decision.

        Args:
            job_id: Original validated job id value.
            request: Original validated request value.

            Returns:
            Original feature response with unchanged fields and validation.

            Raises:
            HTTPException: An original validation or feature error is observed.
        """
        job = self.get_blast_job(job_id, command="plan_discographies")
        with self._blast_jobs_lock:
            pending = job.result.discography_pending_choice
            if job.result.status != "waiting" or pending is None:
                raise HTTPException(
                    status_code=409,
                    detail=("Discography job is not waiting for a choice"),
                )
            self._validate_submission(pending, request)
            job.submitted_choice = request.choice
            job.submitted_order = tuple(request.release_ids)
            job.result.discography_pending_choice = None
            job.result.status = "running"
            job.result.detail = "Discography choice submitted"
            job.choice_event.set()
            return self._blast_job_snapshot(job)

    def cmd_cancel_discography_job(self, job_id: str) -> BlastJobResult:
        """Request a clean stop at the next discography boundary.

        Args:
            job_id: Original validated job id value.

            Returns:
            Original feature response with unchanged fields and validation.

            Raises:
            HTTPException: An original validation or feature error is observed.
        """
        job = self.get_blast_job(job_id, command="plan_discographies")
        with self._blast_jobs_lock:
            if job.result.status not in self._ACTIVE_JOB_STATUSES:
                raise HTTPException(
                    status_code=409, detail=("Discography job is not active")
                )
            job.result.status = "cancelling"
            job.result.discography_pending_choice = None
            job.result.detail = "Stopping discography planning"
            self._append_blast_log_locked(job, job.result.detail)
            job.cancel_event.set()
            job.choice_event.set()
            return self._blast_job_snapshot(job)

    def _validate_submission(
        self, pending: DiscographyPendingChoice, request: DiscographyChoiceRequest
    ) -> None:
        if pending.kind == "artist":
            available = set(option_ids(pending.artist_candidates))
            if request.choice not in available | {"quit"}:
                raise HTTPException(
                    status_code=400, detail=("Spotify artist choice is not available")
                )
        elif pending.kind == "releases":
            if request.choice not in {"select", "none", "quit"}:
                raise HTTPException(
                    status_code=400,
                    detail=("release checklist choice is not available"),
                )
            available = set(option_ids(pending.releases))
            selected = set(request.release_ids)
            if request.choice == ("select") and (
                not request.release_ids
                or len(selected) != len(request.release_ids)
                or (not selected.issubset(available))
            ):
                raise HTTPException(
                    status_code=400, detail=("selected releases are not available")
                )
        elif request.choice not in {"apply", "keep", "quit"}:
            raise HTTPException(
                status_code=400, detail=("final discography choice is not available")
            )
