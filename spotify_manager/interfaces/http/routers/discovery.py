"""Explicit discovery HTTP route registration."""

from collections.abc import Callable

from fastapi import APIRouter
from fastapi import status

from spotify_manager.interfaces.http.models.jobs import BlastJobResult


def router(
    cmd_flush_new_kids: Callable[..., BlastJobResult],
    cmd_active_new_kids_jobs: Callable[..., list[BlastJobResult]],
    cmd_new_kids_job: Callable[..., BlastJobResult],
    cmd_choose_new_kids_release: Callable[..., BlastJobResult],
    cmd_cancel_new_kids_job: Callable[..., BlastJobResult],
) -> APIRouter:
    """Register the original discovery endpoints.

    Args:
        cmd_flush_new_kids: Existing facade handler.
        cmd_active_new_kids_jobs: Existing facade handler.
        cmd_new_kids_job: Existing facade handler.
        cmd_choose_new_kids_release: Existing facade handler.
        cmd_cancel_new_kids_job: Existing facade handler.

    Returns:
        An owned router with unchanged paths, methods and response metadata.
    """
    routes = APIRouter()
    routes.add_api_route(
        "/commands/flush-new-kids",
        cmd_flush_new_kids,
        methods=["POST"],
        response_model=BlastJobResult,
        status_code=status.HTTP_202_ACCEPTED,
    )
    routes.add_api_route(
        "/commands/flush-new-kids-jobs",
        cmd_active_new_kids_jobs,
        methods=["GET"],
        response_model=list[BlastJobResult],
    )
    routes.add_api_route(
        "/commands/flush-new-kids-jobs/{job_id}",
        cmd_new_kids_job,
        methods=["GET"],
        response_model=BlastJobResult,
    )
    routes.add_api_route(
        "/commands/flush-new-kids-jobs/{job_id}/choice",
        cmd_choose_new_kids_release,
        methods=["POST"],
        response_model=BlastJobResult,
    )
    routes.add_api_route(
        "/commands/flush-new-kids-jobs/{job_id}/cancel",
        cmd_cancel_new_kids_job,
        methods=["POST"],
        response_model=BlastJobResult,
    )
    return routes
