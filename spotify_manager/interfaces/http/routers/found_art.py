"""Explicit found art HTTP route registration."""

from collections.abc import Callable

from fastapi import APIRouter
from fastapi import status

from spotify_manager.interfaces.http.models.jobs import BlastJobResult


def router(
    cmd_found_art: Callable[..., BlastJobResult],
    cmd_active_found_art_jobs: Callable[..., list[BlastJobResult]],
    cmd_found_art_job: Callable[..., BlastJobResult],
) -> APIRouter:
    """Register the original found art endpoints.

    Args:
        cmd_found_art: Existing facade handler.
        cmd_active_found_art_jobs: Existing facade handler.
        cmd_found_art_job: Existing facade handler.

    Returns:
        An owned router with unchanged paths, methods and response metadata.
    """
    routes = APIRouter()
    routes.add_api_route(
        "/commands/found-art",
        cmd_found_art,
        methods=["POST"],
        response_model=BlastJobResult,
        status_code=status.HTTP_202_ACCEPTED,
    )
    routes.add_api_route(
        "/commands/found-art-jobs",
        cmd_active_found_art_jobs,
        methods=["GET"],
        response_model=list[BlastJobResult],
    )
    routes.add_api_route(
        "/commands/found-art-jobs/{job_id}",
        cmd_found_art_job,
        methods=["GET"],
        response_model=BlastJobResult,
    )
    return routes
