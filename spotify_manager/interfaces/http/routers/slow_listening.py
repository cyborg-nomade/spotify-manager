"""Explicit slow listening HTTP route registration."""

from collections.abc import Callable

from fastapi import APIRouter
from fastapi import status

from spotify_manager.interfaces.http.models.jobs import BlastJobResult


def router(
    cmd_flush_slow_listening: Callable[..., BlastJobResult],
    cmd_active_slow_listening_jobs: Callable[..., list[BlastJobResult]],
    cmd_slow_listening_job: Callable[..., BlastJobResult],
    cmd_choose_slow_listening_track: Callable[..., BlastJobResult],
    cmd_cancel_slow_listening_job: Callable[..., BlastJobResult],
) -> APIRouter:
    """Register the original slow listening endpoints.

    Args:
        cmd_flush_slow_listening: Existing facade handler.
        cmd_active_slow_listening_jobs: Existing facade handler.
        cmd_slow_listening_job: Existing facade handler.
        cmd_choose_slow_listening_track: Existing facade handler.
        cmd_cancel_slow_listening_job: Existing facade handler.

    Returns:
        An owned router with unchanged paths, methods and response metadata.
    """
    routes = APIRouter()
    routes.add_api_route(
        "/commands/flush-slow-listening",
        cmd_flush_slow_listening,
        methods=["POST"],
        response_model=BlastJobResult,
        status_code=status.HTTP_202_ACCEPTED,
    )
    routes.add_api_route(
        "/commands/flush-slow-listening-jobs",
        cmd_active_slow_listening_jobs,
        methods=["GET"],
        response_model=list[BlastJobResult],
    )
    routes.add_api_route(
        "/commands/flush-slow-listening-jobs/{job_id}",
        cmd_slow_listening_job,
        methods=["GET"],
        response_model=BlastJobResult,
    )
    routes.add_api_route(
        "/commands/flush-slow-listening-jobs/{job_id}/choice",
        cmd_choose_slow_listening_track,
        methods=["POST"],
        response_model=BlastJobResult,
    )
    routes.add_api_route(
        "/commands/flush-slow-listening-jobs/{job_id}/cancel",
        cmd_cancel_slow_listening_job,
        methods=["POST"],
        response_model=BlastJobResult,
    )
    return routes
