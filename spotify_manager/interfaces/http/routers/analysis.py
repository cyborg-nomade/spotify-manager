"""Explicit analysis HTTP route registration."""

from collections.abc import Callable

from fastapi import APIRouter
from fastapi import status

from spotify_manager.interfaces.http.models.analysis import AnalysisJobResult


def router(
    cmd_analyse_library_async: Callable[..., AnalysisJobResult],
    cmd_analyse_library_sync: Callable[..., AnalysisJobResult],
    cmd_refresh_library_mirrors: Callable[..., AnalysisJobResult],
    cmd_refresh_library_mirror_resource: Callable[..., AnalysisJobResult],
    cmd_active_library_analysis_jobs: Callable[..., list[AnalysisJobResult]],
    cmd_library_analysis_job: Callable[..., AnalysisJobResult],
    cmd_cancel_library_analysis_job: Callable[..., AnalysisJobResult],
) -> APIRouter:
    """Register the original analysis endpoints.

    Args:
        cmd_analyse_library_async: Existing facade handler.
        cmd_analyse_library_sync: Existing facade handler.
        cmd_refresh_library_mirrors: Existing facade handler.
        cmd_refresh_library_mirror_resource: Existing facade handler.
        cmd_active_library_analysis_jobs: Existing facade handler.
        cmd_library_analysis_job: Existing facade handler.
        cmd_cancel_library_analysis_job: Existing facade handler.

    Returns:
        An owned router with unchanged paths, methods and response metadata.
    """
    routes = APIRouter()
    routes.add_api_route(
        "/commands/analyse-library-async",
        cmd_analyse_library_async,
        methods=["POST"],
        response_model=AnalysisJobResult,
        status_code=status.HTTP_202_ACCEPTED,
    )
    routes.add_api_route(
        "/commands/analyse-library-sync",
        cmd_analyse_library_sync,
        methods=["POST"],
        response_model=AnalysisJobResult,
        status_code=status.HTTP_202_ACCEPTED,
    )
    routes.add_api_route(
        "/commands/refresh-library-mirrors",
        cmd_refresh_library_mirrors,
        methods=["POST"],
        response_model=AnalysisJobResult,
        status_code=status.HTTP_202_ACCEPTED,
    )
    routes.add_api_route(
        "/commands/refresh-library-mirrors/{resource}",
        cmd_refresh_library_mirror_resource,
        methods=["POST"],
        response_model=AnalysisJobResult,
        status_code=status.HTTP_202_ACCEPTED,
    )
    routes.add_api_route(
        "/commands/library-analysis-jobs",
        cmd_active_library_analysis_jobs,
        methods=["GET"],
        response_model=list[AnalysisJobResult],
    )
    routes.add_api_route(
        "/commands/library-analysis-jobs/{job_id}",
        cmd_library_analysis_job,
        methods=["GET"],
        response_model=AnalysisJobResult,
    )
    routes.add_api_route(
        "/commands/library-analysis-jobs/{job_id}/cancel",
        cmd_cancel_library_analysis_job,
        methods=["POST"],
        response_model=AnalysisJobResult,
    )
    return routes
