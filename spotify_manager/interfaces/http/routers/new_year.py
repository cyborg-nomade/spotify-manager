"""Explicit new year HTTP route registration."""

from collections.abc import Callable

from fastapi import APIRouter

from spotify_manager.interfaces.http.models.jobs import BlastJobResult


def router(
    cmd_new_year: Callable[..., BlastJobResult],
    cmd_active_new_year_jobs: Callable[..., list[BlastJobResult]],
    cmd_new_year_job: Callable[..., BlastJobResult],
    cmd_cancel_new_year_job: Callable[..., BlastJobResult],
) -> APIRouter:
    """Register the original new year endpoints.

    Args:
        cmd_new_year: Existing facade handler.
        cmd_active_new_year_jobs: Existing facade handler.
        cmd_new_year_job: Existing facade handler.
        cmd_cancel_new_year_job: Existing facade handler.

    Returns:
        An owned router with unchanged paths, methods and response metadata.
    """
    routes = APIRouter()
    routes.add_api_route(
        "/commands/new-year",
        cmd_new_year,
        methods=["POST"],
        response_model=BlastJobResult,
        status_code=202,
    )
    routes.add_api_route(
        "/commands/new-year-jobs",
        cmd_active_new_year_jobs,
        methods=["GET"],
        response_model=list[BlastJobResult],
    )
    routes.add_api_route(
        "/commands/new-year-jobs/{job_id}",
        cmd_new_year_job,
        methods=["GET"],
        response_model=BlastJobResult,
    )
    routes.add_api_route(
        "/commands/new-year-jobs/{job_id}/cancel",
        cmd_cancel_new_year_job,
        methods=["POST"],
        response_model=BlastJobResult,
    )
    return routes
