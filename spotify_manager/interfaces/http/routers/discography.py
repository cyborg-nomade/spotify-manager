"""Explicit discography HTTP route registration."""

from collections.abc import Callable

from fastapi import APIRouter
from fastapi import status

from spotify_manager.interfaces.http.models.jobs import BlastJobResult


def router(
    cmd_plan_discographies: Callable[..., BlastJobResult],
    cmd_active_discography_jobs: Callable[..., list[BlastJobResult]],
    cmd_discography_job: Callable[..., BlastJobResult],
    cmd_choose_discography: Callable[..., BlastJobResult],
    cmd_cancel_discography_job: Callable[..., BlastJobResult],
) -> APIRouter:
    """Register the original discography endpoints.

    Args:
        cmd_plan_discographies: Existing facade handler.
        cmd_active_discography_jobs: Existing facade handler.
        cmd_discography_job: Existing facade handler.
        cmd_choose_discography: Existing facade handler.
        cmd_cancel_discography_job: Existing facade handler.

    Returns:
        An owned router with unchanged paths, methods and response metadata.
    """
    routes = APIRouter()
    routes.add_api_route(
        "/commands/plan-discographies",
        cmd_plan_discographies,
        methods=["POST"],
        response_model=BlastJobResult,
        status_code=status.HTTP_202_ACCEPTED,
    )
    routes.add_api_route(
        "/commands/plan-discographies-jobs",
        cmd_active_discography_jobs,
        methods=["GET"],
        response_model=list[BlastJobResult],
    )
    routes.add_api_route(
        "/commands/plan-discographies-jobs/{job_id}",
        cmd_discography_job,
        methods=["GET"],
        response_model=BlastJobResult,
    )
    routes.add_api_route(
        "/commands/plan-discographies-jobs/{job_id}/choice",
        cmd_choose_discography,
        methods=["POST"],
        response_model=BlastJobResult,
    )
    routes.add_api_route(
        "/commands/plan-discographies-jobs/{job_id}/cancel",
        cmd_cancel_discography_job,
        methods=["POST"],
        response_model=BlastJobResult,
    )
    return routes
