"""Explicit queue flush HTTP route registration."""

from collections.abc import Callable

from fastapi import APIRouter
from fastapi import status

from spotify_manager.interfaces.http.models.jobs import BlastJobResult


def router(
    cmd_flush_queue: Callable[..., BlastJobResult],
    cmd_active_queue_flush_jobs: Callable[..., list[BlastJobResult]],
    cmd_queue_flush_job: Callable[..., BlastJobResult],
    cmd_cancel_queue_flush_job: Callable[..., BlastJobResult],
) -> APIRouter:
    """Register the original queue flush endpoints.

    Args:
        cmd_flush_queue: Existing facade handler.
        cmd_active_queue_flush_jobs: Existing facade handler.
        cmd_queue_flush_job: Existing facade handler.
        cmd_cancel_queue_flush_job: Existing facade handler.

    Returns:
        An owned router with unchanged paths, methods and response metadata.
    """
    routes = APIRouter()
    routes.add_api_route(
        "/commands/flush-queue",
        cmd_flush_queue,
        methods=["POST"],
        response_model=BlastJobResult,
        status_code=status.HTTP_202_ACCEPTED,
    )
    routes.add_api_route(
        "/commands/flush-queue-jobs",
        cmd_active_queue_flush_jobs,
        methods=["GET"],
        response_model=list[BlastJobResult],
    )
    routes.add_api_route(
        "/commands/flush-queue-jobs/{job_id}",
        cmd_queue_flush_job,
        methods=["GET"],
        response_model=BlastJobResult,
    )
    routes.add_api_route(
        "/commands/flush-queue-jobs/{job_id}/cancel",
        cmd_cancel_queue_flush_job,
        methods=["POST"],
        response_model=BlastJobResult,
    )
    return routes
