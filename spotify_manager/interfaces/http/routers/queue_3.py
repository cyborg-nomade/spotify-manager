"""Explicit queue 3 HTTP route registration."""

from collections.abc import Callable

from fastapi import APIRouter
from fastapi import status

from spotify_manager.interfaces.http.models.jobs import BlastJobResult


def router(
    cmd_flush_queue_3: Callable[..., BlastJobResult],
    cmd_import_queue_3_previous_year: Callable[..., BlastJobResult],
    cmd_active_queue_3_jobs: Callable[..., list[BlastJobResult]],
    cmd_queue_3_job: Callable[..., BlastJobResult],
    cmd_choose_queue_3: Callable[..., BlastJobResult],
    cmd_cancel_queue_3_job: Callable[..., BlastJobResult],
) -> APIRouter:
    """Register the original queue 3 endpoints.

    Args:
        cmd_flush_queue_3: Existing facade handler.
        cmd_import_queue_3_previous_year: Existing facade handler.
        cmd_active_queue_3_jobs: Existing facade handler.
        cmd_queue_3_job: Existing facade handler.
        cmd_choose_queue_3: Existing facade handler.
        cmd_cancel_queue_3_job: Existing facade handler.

    Returns:
        An owned router with unchanged paths, methods and response metadata.
    """
    routes = APIRouter()
    routes.add_api_route(
        "/commands/flush-queue-3",
        cmd_flush_queue_3,
        methods=["POST"],
        response_model=BlastJobResult,
        status_code=status.HTTP_202_ACCEPTED,
    )
    routes.add_api_route(
        "/commands/import-queue-3-previous-year",
        cmd_import_queue_3_previous_year,
        methods=["POST"],
        response_model=BlastJobResult,
        status_code=status.HTTP_202_ACCEPTED,
    )
    routes.add_api_route(
        "/commands/flush-queue-3-jobs",
        cmd_active_queue_3_jobs,
        methods=["GET"],
        response_model=list[BlastJobResult],
    )
    routes.add_api_route(
        "/commands/flush-queue-3-jobs/{job_id}",
        cmd_queue_3_job,
        methods=["GET"],
        response_model=BlastJobResult,
    )
    routes.add_api_route(
        "/commands/flush-queue-3-jobs/{job_id}/choice",
        cmd_choose_queue_3,
        methods=["POST"],
        response_model=BlastJobResult,
    )
    routes.add_api_route(
        "/commands/flush-queue-3-jobs/{job_id}/cancel",
        cmd_cancel_queue_3_job,
        methods=["POST"],
        response_model=BlastJobResult,
    )
    return routes
