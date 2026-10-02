"""Explicit queue fill HTTP route registration."""

from collections.abc import Callable

from fastapi import APIRouter
from fastapi import status

from spotify_manager.interfaces.http.models.jobs import BlastJobResult


def router(
    cmd_fill_queue_from_lastfm: Callable[..., BlastJobResult],
    cmd_active_queue_fill_jobs: Callable[..., list[BlastJobResult]],
    cmd_queue_fill_job: Callable[..., BlastJobResult],
    cmd_choose_queue_artist: Callable[..., BlastJobResult],
    cmd_cancel_queue_fill_job: Callable[..., BlastJobResult],
) -> APIRouter:
    """Register the original queue fill endpoints.

    Args:
        cmd_fill_queue_from_lastfm: Existing facade handler.
        cmd_active_queue_fill_jobs: Existing facade handler.
        cmd_queue_fill_job: Existing facade handler.
        cmd_choose_queue_artist: Existing facade handler.
        cmd_cancel_queue_fill_job: Existing facade handler.

    Returns:
        An owned router with unchanged paths, methods and response metadata.
    """
    routes = APIRouter()
    routes.add_api_route(
        "/commands/fill-queue-from-lastfm",
        cmd_fill_queue_from_lastfm,
        methods=["POST"],
        response_model=BlastJobResult,
        status_code=status.HTTP_202_ACCEPTED,
    )
    routes.add_api_route(
        "/commands/fill-queue-from-lastfm-jobs",
        cmd_active_queue_fill_jobs,
        methods=["GET"],
        response_model=list[BlastJobResult],
    )
    routes.add_api_route(
        "/commands/fill-queue-from-lastfm-jobs/{job_id}",
        cmd_queue_fill_job,
        methods=["GET"],
        response_model=BlastJobResult,
    )
    routes.add_api_route(
        "/commands/fill-queue-from-lastfm-jobs/{job_id}/choice",
        cmd_choose_queue_artist,
        methods=["POST"],
        response_model=BlastJobResult,
    )
    routes.add_api_route(
        "/commands/fill-queue-from-lastfm-jobs/{job_id}/cancel",
        cmd_cancel_queue_fill_job,
        methods=["POST"],
        response_model=BlastJobResult,
    )
    return routes
