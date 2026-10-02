"""Explicit requeue HTTP route registration."""

from collections.abc import Callable

from fastapi import APIRouter
from fastapi import status

from spotify_manager.interfaces.http.models.jobs import BlastJobResult


def router(
    cmd_flush_requeue_for_a_dream: Callable[..., BlastJobResult],
    cmd_active_requeue_for_a_dream_jobs: Callable[..., list[BlastJobResult]],
    cmd_requeue_for_a_dream_job: Callable[..., BlastJobResult],
    cmd_cancel_requeue_for_a_dream_job: Callable[..., BlastJobResult],
) -> APIRouter:
    """Register the original requeue endpoints.

    Args:
        cmd_flush_requeue_for_a_dream: Existing facade handler.
        cmd_active_requeue_for_a_dream_jobs: Existing facade handler.
        cmd_requeue_for_a_dream_job: Existing facade handler.
        cmd_cancel_requeue_for_a_dream_job: Existing facade handler.

    Returns:
        An owned router with unchanged paths, methods and response metadata.
    """
    routes = APIRouter()
    routes.add_api_route(
        "/commands/flush-requeue-for-a-dream",
        cmd_flush_requeue_for_a_dream,
        methods=["POST"],
        response_model=BlastJobResult,
        status_code=status.HTTP_202_ACCEPTED,
    )
    routes.add_api_route(
        "/commands/flush-requeue-for-a-dream-jobs",
        cmd_active_requeue_for_a_dream_jobs,
        methods=["GET"],
        response_model=list[BlastJobResult],
    )
    routes.add_api_route(
        "/commands/flush-requeue-for-a-dream-jobs/{job_id}",
        cmd_requeue_for_a_dream_job,
        methods=["GET"],
        response_model=BlastJobResult,
    )
    routes.add_api_route(
        "/commands/flush-requeue-for-a-dream-jobs/{job_id}/cancel",
        cmd_cancel_requeue_for_a_dream_job,
        methods=["POST"],
        response_model=BlastJobResult,
    )
    return routes
