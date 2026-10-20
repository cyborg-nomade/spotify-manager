"""Validate and present releases HTTP requests."""

from fastapi import HTTPException
from spotipy import Spotify

from spotify_manager.core.state.models import StateConfigurationError
from spotify_manager.core.state.models import StateConflictError
from spotify_manager.core.state.models import StateError
from spotify_manager.interfaces.http import jobs
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


def cmd_check_new_releases(client: Spotify, dry_run: bool) -> BlastJobResult:
    """Start a reconnectable release check for Last.fm's top artists.

    Args:
        client: Original validated client value.
        dry_run: Original validated dry run value.

    Returns:
        Original feature response with unchanged fields and validation.

    Raises:
        HTTPException: An original validation or feature error is observed.
    """
    configuration = jobs.Settings()
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
    return jobs.start_release_check_job(
        client, playlists, api_key, username, dry_run=dry_run
    )


def cmd_release_check_state(known_fingerprint: str | None) -> ReleaseCheckStateSnapshot:
    """Return restart state, omitting the payload when the browser is current.

    Args:
        known_fingerprint: Original validated known fingerprint value.

    Returns:
        Original feature response with unchanged fields and validation.

    Raises:
        HTTPException: An original validation or feature error is observed.
    """
    try:
        return jobs._release_check_state_snapshot(known_fingerprint)
    except (release_check.ReleaseCheckStateError, StateError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def cmd_restore_release_check_state(
    request: ReleaseCheckStateRestoreRequest,
) -> ReleaseCheckStateSnapshot:
    """Restore a newer browser mirror without overwriting concurrent progress.

    Args:
        request: Original validated request value.

    Returns:
        Original feature response with unchanged fields and validation.

    Raises:
        HTTPException: An original validation or feature error is observed.
    """
    with jobs._blast_jobs_lock:
        if _has_active_release_check():
            raise HTTPException(
                status_code=409,
                detail="New-release check is active; state restore was not applied",
            )
        return _restore_state_locked(request)


def cmd_active_release_check_jobs() -> list[BlastJobResult]:
    """Return active release checks for page-reload reconnection.

    Returns:
        Original feature response with unchanged fields and validation.
    """
    return jobs._active_playlist_jobs("check_new_releases")


def cmd_release_check_job(job_id: str) -> BlastJobResult:
    """Return release-check progress and any pending interaction.

    Args:
        job_id: Original validated job id value.

    Returns:
        Original feature response with unchanged fields and validation.
    """
    job = jobs.get_blast_job(job_id, command="check_new_releases")
    with jobs._blast_jobs_lock:
        return jobs._blast_job_snapshot(job)


def cmd_choose_release_check(
    job_id: str, request: ReleaseCheckChoiceRequest
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
    job = jobs.get_blast_job(job_id, command="check_new_releases")
    with jobs._blast_jobs_lock:
        pending = job.result.release_check_pending_choice
        if job.result.status != "waiting" or pending is None:
            raise HTTPException(
                status_code=409, detail="New-release check is not waiting for a choice"
            )
        _validate_submission(pending, request)
        job.submitted_choice = request.choice
        job.result.release_check_pending_choice = None
        job.result.status = "running"
        job.result.detail = "Release-check choice submitted"
        job.choice_event.set()
        return jobs._blast_job_snapshot(job)


def cmd_cancel_release_check_job(job_id: str) -> BlastJobResult:
    """Request a clean stop at the next release-check boundary.

    Args:
        job_id: Original validated job id value.

    Returns:
        Original feature response with unchanged fields and validation.

    Raises:
        HTTPException: An original validation or feature error is observed.
    """
    job = jobs.get_blast_job(job_id, command="check_new_releases")
    with jobs._blast_jobs_lock:
        if job.result.status not in jobs._ACTIVE_JOB_STATUSES:
            raise HTTPException(
                status_code=409, detail="New-release check is not active"
            )
        job.result.status = "cancelling"
        job.result.release_check_pending_choice = None
        job.result.detail = "Stopping new-release check"
        jobs._append_blast_log_locked(job, job.result.detail)
        job.cancel_event.set()
        job.choice_event.set()
        return jobs._blast_job_snapshot(job)


def _validate_submission(
    pending: ReleaseCheckPendingChoice, request: ReleaseCheckChoiceRequest
) -> None:
    if pending.kind == "artist":
        allowed = {
            release_check.CHOICE_SKIP,
            release_check.CHOICE_SKIP_ARTIST,
            release_check.CHOICE_QUIT,
            *option_ids(pending.artist_candidates),
        }
        custom_search = request.choice.startswith(release_check.CHOICE_SEARCH_PREFIX)
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
    request: ReleaseCheckStateRestoreRequest,
) -> ReleaseCheckStateSnapshot:
    try:
        candidate = release_check.validate_state(request.state)
        state_access = jobs.get_state_service().namespace(
            "release_check", jobs.STATE_NAMESPACE_DEFINITIONS["release_check"]
        )
        current = state_access.load()
        current_fingerprint = release_check.state_fingerprint(current)
        if current_fingerprint != request.expected_server_fingerprint:
            raise HTTPException(
                status_code=409,
                detail="Release-check state changed; reload before restoring",
            )
        if not jobs._release_state_is_newer(candidate, current):
            raise HTTPException(
                status_code=409, detail="Browser release-check state is not newer"
            )
        state_access.save(
            candidate, message="Restore newer browser release-check state"
        )
        return jobs._release_check_state_snapshot()
    except StateConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except StateConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except release_check.ReleaseCheckStateError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _has_active_release_check() -> bool:
    for job in jobs._blast_jobs.values():
        if job.result.command != "check_new_releases":
            continue
        if job.result.status in jobs._ACTIVE_JOB_STATUSES:
            return True
    return False
