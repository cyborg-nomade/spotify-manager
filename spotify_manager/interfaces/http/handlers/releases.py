"""Original releases HTTP validation and job interactions."""

from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock

from fastapi import HTTPException
from spotipy import Spotify

from spotify_manager.core.state.models import StateConfigurationError
from spotify_manager.core.state.models import StateConflictError
from spotify_manager.core.state.models import StateError
from spotify_manager.core.state.service import StateService
from spotify_manager.interfaces.http.job_records import PlaylistJob as _BlastJob
from spotify_manager.interfaces.http.models.jobs import BlastJobResult
from spotify_manager.interfaces.http.models.releases import ReleaseCheckChoiceRequest
from spotify_manager.interfaces.http.models.releases import ReleaseCheckPendingChoice
from spotify_manager.interfaces.http.models.releases import (
    ReleaseCheckStateRestoreRequest,
)
from spotify_manager.interfaces.http.models.releases import ReleaseCheckStateSnapshot
from spotify_manager.interfaces.http.validation import option_ids
from spotify_manager.interfaces.operations import found_art as found_art
from spotify_manager.interfaces.operations import release_check as release_check
from spotify_manager.settings import Settings


@dataclass(kw_only=True)
class ReleasesHandlers:
    """Validate and present one feature through explicit facade dependencies.

    Args:
        Settings: Existing overridable feature dependency.
        _ACTIVE_JOB_STATUSES: Existing overridable feature dependency.
        _active_playlist_jobs: Existing overridable feature dependency.
        _append_blast_log_locked: Existing overridable feature dependency.
        _blast_job_snapshot: Existing overridable feature dependency.
        _blast_jobs: Existing overridable feature dependency.
        _blast_jobs_lock: Existing overridable feature dependency.
        _release_check_state_snapshot: Existing overridable feature dependency.
        _release_state_is_newer: Existing overridable feature dependency.
        get_blast_job: Existing overridable feature dependency.
        get_state_service: Existing overridable feature dependency.
        start_release_check_job: Existing overridable feature dependency.
    """

    Settings: type[Settings]
    _ACTIVE_JOB_STATUSES: set[str]
    _active_playlist_jobs: Callable[..., list[BlastJobResult]]
    _append_blast_log_locked: Callable[..., None]
    _blast_job_snapshot: Callable[..., BlastJobResult]
    _blast_jobs: dict[str, _BlastJob]
    _blast_jobs_lock: Lock
    _release_check_state_snapshot: Callable[..., ReleaseCheckStateSnapshot]
    _release_state_is_newer: Callable[..., bool]
    get_blast_job: Callable[..., _BlastJob]
    get_state_service: Callable[..., StateService]
    start_release_check_job: Callable[..., BlastJobResult]

    def cmd_check_new_releases(self, client: Spotify, dry_run: bool) -> BlastJobResult:
        """Start a reconnectable release check for Last.fm's top artists.

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
            playlists = release_check.ReleaseCheckPlaylists.from_references(
                configuration.wine_cellar_playlist, configuration.new_vintage_playlist
            )
            api_key, username = found_art.validate_lastfm_configuration(
                configuration.lastfm_api_key, configuration.lastfm_username
            )
        except (
            release_check.ReleaseCheckConfigError,
            found_art.FoundArtConfigError,
        ) as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return self.start_release_check_job(
            client, playlists, api_key, username, dry_run=dry_run
        )

    def cmd_release_check_state(
        self, known_fingerprint: str | None
    ) -> ReleaseCheckStateSnapshot:
        """Return restart state, omitting the payload when the browser is current.

        Args:
            known_fingerprint: Original validated known fingerprint value.

        Returns:
            Original feature response with unchanged fields and validation.

        Raises:
            HTTPException: An original validation or feature error is observed.
        """
        try:
            return self._release_check_state_snapshot(known_fingerprint)
        except (release_check.ReleaseCheckStateError, StateError) as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    def cmd_restore_release_check_state(
        self, request: ReleaseCheckStateRestoreRequest
    ) -> ReleaseCheckStateSnapshot:
        """Restore a newer browser mirror without overwriting concurrent progress.

        Args:
            request: Original validated request value.

        Returns:
            Original feature response with unchanged fields and validation.

        Raises:
            HTTPException: An original validation or feature error is observed.
        """
        with self._blast_jobs_lock:
            if self._has_active_release_check():
                raise HTTPException(
                    status_code=409,
                    detail="New-release check is active; state restore was not applied",
                )
            return self._restore_state_locked(request)

    def cmd_active_release_check_jobs(self) -> list[BlastJobResult]:
        """Return active release checks for page-reload reconnection.

        Returns:
            Original feature response with unchanged fields and validation.
        """
        return self._active_playlist_jobs("check_new_releases")

    def cmd_release_check_job(self, job_id: str) -> BlastJobResult:
        """Return release-check progress and any pending interaction.

        Args:
            job_id: Original validated job id value.

        Returns:
            Original feature response with unchanged fields and validation.
        """
        job = self.get_blast_job(job_id, command="check_new_releases")
        with self._blast_jobs_lock:
            return self._blast_job_snapshot(job)

    def cmd_choose_release_check(
        self, job_id: str, request: ReleaseCheckChoiceRequest
    ) -> BlastJobResult:
        """Submit an artist mapping, custom search, or release decision.

        Args:
            job_id: Original validated job id value.
            request: Original validated request value.

        Returns:
            Original feature response with unchanged fields and validation.

        Raises:
            HTTPException: An original validation or feature error is observed.
        """
        job = self.get_blast_job(job_id, command="check_new_releases")
        with self._blast_jobs_lock:
            pending = job.result.release_check_pending_choice
            if job.result.status != "waiting" or pending is None:
                raise HTTPException(
                    status_code=409,
                    detail="New-release check is not waiting for a choice",
                )
            self._validate_submission(pending, request)
            job.submitted_choice = request.choice
            job.result.release_check_pending_choice = None
            job.result.status = "running"
            job.result.detail = "Release-check choice submitted"
            job.choice_event.set()
            return self._blast_job_snapshot(job)

    def cmd_cancel_release_check_job(self, job_id: str) -> BlastJobResult:
        """Request a clean stop at the next release-check boundary.

        Args:
            job_id: Original validated job id value.

        Returns:
            Original feature response with unchanged fields and validation.

        Raises:
            HTTPException: An original validation or feature error is observed.
        """
        job = self.get_blast_job(job_id, command="check_new_releases")
        with self._blast_jobs_lock:
            if job.result.status not in self._ACTIVE_JOB_STATUSES:
                raise HTTPException(
                    status_code=409, detail="New-release check is not active"
                )
            job.result.status = "cancelling"
            job.result.release_check_pending_choice = None
            job.result.detail = "Stopping new-release check"
            self._append_blast_log_locked(job, job.result.detail)
            job.cancel_event.set()
            job.choice_event.set()
            return self._blast_job_snapshot(job)

    def _validate_submission(
        self, pending: ReleaseCheckPendingChoice, request: ReleaseCheckChoiceRequest
    ) -> None:
        if pending.kind == "artist":
            allowed = {
                release_check.CHOICE_SKIP,
                release_check.CHOICE_SKIP_ARTIST,
                release_check.CHOICE_QUIT,
                *option_ids(pending.artist_candidates),
            }
            custom_search = request.choice.startswith(
                release_check.CHOICE_SEARCH_PREFIX
            )
            search_text = request.choice.removeprefix(
                release_check.CHOICE_SEARCH_PREFIX
            ).strip()
            if request.choice not in allowed and (not (custom_search and search_text)):
                raise HTTPException(
                    status_code=400, detail="artist mapping choice is not available"
                )
        elif request.choice not in {
            release_check.CHOICE_ADD,
            release_check.CHOICE_PENDING,
            release_check.CHOICE_SKIP,
            release_check.CHOICE_QUIT,
        } or (
            request.choice == release_check.CHOICE_PENDING
            and (not pending.unattached_single)
        ):
            raise HTTPException(
                status_code=400, detail="release review choice is not available"
            )

    def _restore_state_locked(
        self, request: ReleaseCheckStateRestoreRequest
    ) -> ReleaseCheckStateSnapshot:
        try:
            candidate = release_check.validate_state(request.state)
            state_access = self.get_state_service().namespace(
                "release_check",
                release_check._default_state,
                release_check.validate_state,
            )
            current = state_access.load()
            current_fingerprint = release_check.state_fingerprint(current)
            if current_fingerprint != request.expected_server_fingerprint:
                raise HTTPException(
                    status_code=409,
                    detail="Release-check state changed; reload before restoring",
                )
            if not self._release_state_is_newer(candidate, current):
                raise HTTPException(
                    status_code=409, detail="Browser release-check state is not newer"
                )
            state_access.save(
                candidate, message="Restore newer browser release-check state"
            )
            return self._release_check_state_snapshot()
        except StateConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except StateConfigurationError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except release_check.ReleaseCheckStateError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    def _has_active_release_check(self) -> bool:
        for job in self._blast_jobs.values():
            if job.result.command != "check_new_releases":
                continue
            if job.result.status in self._ACTIVE_JOB_STATUSES:
                return True
        return False
