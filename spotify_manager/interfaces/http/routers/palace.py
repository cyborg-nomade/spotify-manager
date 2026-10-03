"""Explicit palace HTTP route registration."""

from collections.abc import Callable

from fastapi import APIRouter
from fastapi import status

from spotify_manager.interfaces.http.models.jobs import BlastJobResult


def router(
    cmd_fill_palace_of_memory: Callable[..., BlastJobResult],
    cmd_active_palace_of_memory_jobs: Callable[..., list[BlastJobResult]],
    cmd_palace_of_memory_job: Callable[..., BlastJobResult],
    cmd_cancel_palace_of_memory_job: Callable[..., BlastJobResult],
) -> APIRouter:
    """Register the original palace endpoints.

    Args:
        cmd_fill_palace_of_memory: Existing facade handler.
        cmd_active_palace_of_memory_jobs: Existing facade handler.
        cmd_palace_of_memory_job: Existing facade handler.
        cmd_cancel_palace_of_memory_job: Existing facade handler.

    Returns:
        An owned router with unchanged paths, methods and response metadata.
    """
    routes = APIRouter()
    routes.add_api_route(
        "/commands/fill-palace-of-memory",
        cmd_fill_palace_of_memory,
        methods=["POST"],
        response_model=BlastJobResult,
        status_code=status.HTTP_202_ACCEPTED,
    )
    routes.add_api_route(
        "/commands/fill-palace-of-memory-jobs",
        cmd_active_palace_of_memory_jobs,
        methods=["GET"],
        response_model=list[BlastJobResult],
    )
    routes.add_api_route(
        "/commands/fill-palace-of-memory-jobs/{job_id}",
        cmd_palace_of_memory_job,
        methods=["GET"],
        response_model=BlastJobResult,
    )
    routes.add_api_route(
        "/commands/fill-palace-of-memory-jobs/{job_id}/cancel",
        cmd_cancel_palace_of_memory_job,
        methods=["POST"],
        response_model=BlastJobResult,
    )
    return routes
