"""Explicit something old HTTP route registration."""

from collections.abc import Callable

from fastapi import APIRouter
from fastapi import status

from spotify_manager.interfaces.http.models.jobs import BlastJobResult


def router(
    cmd_something_old: Callable[..., BlastJobResult],
    cmd_active_something_old_jobs: Callable[..., list[BlastJobResult]],
    cmd_something_old_job: Callable[..., BlastJobResult],
    cmd_choose_something_old: Callable[..., BlastJobResult],
    cmd_cancel_something_old_job: Callable[..., BlastJobResult],
) -> APIRouter:
    """Register the original something old endpoints.

    Args:
        cmd_something_old: Existing facade handler.
        cmd_active_something_old_jobs: Existing facade handler.
        cmd_something_old_job: Existing facade handler.
        cmd_choose_something_old: Existing facade handler.
        cmd_cancel_something_old_job: Existing facade handler.

    Returns:
        An owned router with unchanged paths, methods and response metadata.
    """
    routes = APIRouter()
    routes.add_api_route(
        "/commands/something-old",
        cmd_something_old,
        methods=["POST"],
        response_model=BlastJobResult,
        status_code=status.HTTP_202_ACCEPTED,
    )
    routes.add_api_route(
        "/commands/something-old-jobs",
        cmd_active_something_old_jobs,
        methods=["GET"],
        response_model=list[BlastJobResult],
    )
    routes.add_api_route(
        "/commands/something-old-jobs/{job_id}",
        cmd_something_old_job,
        methods=["GET"],
        response_model=BlastJobResult,
    )
    routes.add_api_route(
        "/commands/something-old-jobs/{job_id}/choice",
        cmd_choose_something_old,
        methods=["POST"],
        response_model=BlastJobResult,
    )
    routes.add_api_route(
        "/commands/something-old-jobs/{job_id}/cancel",
        cmd_cancel_something_old_job,
        methods=["POST"],
        response_model=BlastJobResult,
    )
    return routes
