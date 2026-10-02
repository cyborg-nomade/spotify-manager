"""Explicit daily mind radio HTTP route registration."""

from collections.abc import Callable

from fastapi import APIRouter
from fastapi import status

from spotify_manager.interfaces.http.models.jobs import BlastJobResult


def router(
    cmd_daily_mind_radio: Callable[..., BlastJobResult],
    cmd_active_daily_mind_radio_jobs: Callable[..., list[BlastJobResult]],
    cmd_daily_mind_radio_job: Callable[..., BlastJobResult],
    cmd_cancel_daily_mind_radio_job: Callable[..., BlastJobResult],
) -> APIRouter:
    """Register the original daily mind radio endpoints.

    Args:
        cmd_daily_mind_radio: Existing facade handler.
        cmd_active_daily_mind_radio_jobs: Existing facade handler.
        cmd_daily_mind_radio_job: Existing facade handler.
        cmd_cancel_daily_mind_radio_job: Existing facade handler.

    Returns:
        An owned router with unchanged paths, methods and response metadata.
    """
    routes = APIRouter()
    routes.add_api_route(
        "/commands/daily-mind-radio",
        cmd_daily_mind_radio,
        methods=["POST"],
        response_model=BlastJobResult,
        status_code=status.HTTP_202_ACCEPTED,
    )
    routes.add_api_route(
        "/commands/daily-mind-radio-jobs",
        cmd_active_daily_mind_radio_jobs,
        methods=["GET"],
        response_model=list[BlastJobResult],
    )
    routes.add_api_route(
        "/commands/daily-mind-radio-jobs/{job_id}",
        cmd_daily_mind_radio_job,
        methods=["GET"],
        response_model=BlastJobResult,
    )
    routes.add_api_route(
        "/commands/daily-mind-radio-jobs/{job_id}/cancel",
        cmd_cancel_daily_mind_radio_job,
        methods=["POST"],
        response_model=BlastJobResult,
    )
    return routes
