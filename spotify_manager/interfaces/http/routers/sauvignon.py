"""Explicit sauvignon HTTP route registration."""

from collections.abc import Callable

from fastapi import APIRouter
from fastapi import status

from spotify_manager.interfaces.http.models.jobs import BlastJobResult


def router(
    cmd_fill_sauvignon_from_lastfm: Callable[..., BlastJobResult],
    cmd_active_sauvignon_jobs: Callable[..., list[BlastJobResult]],
    cmd_sauvignon_job: Callable[..., BlastJobResult],
    cmd_choose_sauvignon_album: Callable[..., BlastJobResult],
    cmd_cancel_sauvignon_job: Callable[..., BlastJobResult],
) -> APIRouter:
    """Register the original sauvignon endpoints.

    Args:
        cmd_fill_sauvignon_from_lastfm: Existing facade handler.
        cmd_active_sauvignon_jobs: Existing facade handler.
        cmd_sauvignon_job: Existing facade handler.
        cmd_choose_sauvignon_album: Existing facade handler.
        cmd_cancel_sauvignon_job: Existing facade handler.

    Returns:
        An owned router with unchanged paths, methods and response metadata.
    """
    routes = APIRouter()
    routes.add_api_route(
        "/commands/fill-sauvignon-from-lastfm",
        cmd_fill_sauvignon_from_lastfm,
        methods=["POST"],
        response_model=BlastJobResult,
        status_code=status.HTTP_202_ACCEPTED,
    )
    routes.add_api_route(
        "/commands/fill-sauvignon-from-lastfm-jobs",
        cmd_active_sauvignon_jobs,
        methods=["GET"],
        response_model=list[BlastJobResult],
    )
    routes.add_api_route(
        "/commands/fill-sauvignon-from-lastfm-jobs/{job_id}",
        cmd_sauvignon_job,
        methods=["GET"],
        response_model=BlastJobResult,
    )
    routes.add_api_route(
        "/commands/fill-sauvignon-from-lastfm-jobs/{job_id}/choice",
        cmd_choose_sauvignon_album,
        methods=["POST"],
        response_model=BlastJobResult,
    )
    routes.add_api_route(
        "/commands/fill-sauvignon-from-lastfm-jobs/{job_id}/cancel",
        cmd_cancel_sauvignon_job,
        methods=["POST"],
        response_model=BlastJobResult,
    )
    return routes
