"""Explicit releases HTTP route registration."""

from collections.abc import Callable

from fastapi import APIRouter
from fastapi import status

from spotify_manager.interfaces.http.models.jobs import BlastJobResult
from spotify_manager.interfaces.http.models.releases import ReleaseCheckStateSnapshot


def router(
    cmd_check_new_releases: Callable[..., BlastJobResult],
    cmd_release_check_state: Callable[..., ReleaseCheckStateSnapshot],
    cmd_restore_release_check_state: Callable[..., ReleaseCheckStateSnapshot],
    cmd_active_release_check_jobs: Callable[..., list[BlastJobResult]],
    cmd_release_check_job: Callable[..., BlastJobResult],
    cmd_choose_release_check: Callable[..., BlastJobResult],
    cmd_cancel_release_check_job: Callable[..., BlastJobResult],
) -> APIRouter:
    """Register the original releases endpoints.

    Args:
        cmd_check_new_releases: Existing facade handler.
        cmd_release_check_state: Existing facade handler.
        cmd_restore_release_check_state: Existing facade handler.
        cmd_active_release_check_jobs: Existing facade handler.
        cmd_release_check_job: Existing facade handler.
        cmd_choose_release_check: Existing facade handler.
        cmd_cancel_release_check_job: Existing facade handler.

    Returns:
        An owned router with unchanged paths, methods and response metadata.
    """
    routes = APIRouter()
    routes.add_api_route(
        "/commands/check-new-releases",
        cmd_check_new_releases,
        methods=["POST"],
        response_model=BlastJobResult,
        status_code=status.HTTP_202_ACCEPTED,
    )
    routes.add_api_route(
        "/commands/check-new-releases-state",
        cmd_release_check_state,
        methods=["GET"],
        response_model=ReleaseCheckStateSnapshot,
    )
    routes.add_api_route(
        "/commands/check-new-releases-state",
        cmd_restore_release_check_state,
        methods=["PUT"],
        response_model=ReleaseCheckStateSnapshot,
    )
    routes.add_api_route(
        "/commands/check-new-releases-jobs",
        cmd_active_release_check_jobs,
        methods=["GET"],
        response_model=list[BlastJobResult],
    )
    routes.add_api_route(
        "/commands/check-new-releases-jobs/{job_id}",
        cmd_release_check_job,
        methods=["GET"],
        response_model=BlastJobResult,
    )
    routes.add_api_route(
        "/commands/check-new-releases-jobs/{job_id}/choice",
        cmd_choose_release_check,
        methods=["POST"],
        response_model=BlastJobResult,
    )
    routes.add_api_route(
        "/commands/check-new-releases-jobs/{job_id}/cancel",
        cmd_cancel_release_check_job,
        methods=["POST"],
        response_model=BlastJobResult,
    )
    return routes
