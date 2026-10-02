"""Explicit historical HTTP route registration."""

from collections.abc import Callable

from fastapi import APIRouter
from fastapi import status

from spotify_manager.interfaces.http.models.jobs import BlastJobResult


def router(
    cmd_blast_from_the_past: Callable[..., BlastJobResult],
    cmd_active_blast_jobs: Callable[..., list[BlastJobResult]],
    cmd_blast_job: Callable[..., BlastJobResult],
    cmd_cancel_blast_job: Callable[..., BlastJobResult],
) -> APIRouter:
    """Register the original historical endpoints.

    Args:
        cmd_blast_from_the_past: Existing facade handler.
        cmd_active_blast_jobs: Existing facade handler.
        cmd_blast_job: Existing facade handler.
        cmd_cancel_blast_job: Existing facade handler.

    Returns:
        An owned router with unchanged paths, methods and response metadata.
    """
    routes = APIRouter()
    routes.add_api_route(
        "/commands/blast-from-the-past",
        cmd_blast_from_the_past,
        methods=["POST"],
        response_model=BlastJobResult,
        status_code=status.HTTP_202_ACCEPTED,
    )
    routes.add_api_route(
        "/commands/blast-from-the-past-jobs",
        cmd_active_blast_jobs,
        methods=["GET"],
        response_model=list[BlastJobResult],
    )
    routes.add_api_route(
        "/commands/blast-from-the-past-jobs/{job_id}",
        cmd_blast_job,
        methods=["GET"],
        response_model=BlastJobResult,
    )
    routes.add_api_route(
        "/commands/blast-from-the-past-jobs/{job_id}/cancel",
        cmd_cancel_blast_job,
        methods=["POST"],
        response_model=BlastJobResult,
    )
    return routes
