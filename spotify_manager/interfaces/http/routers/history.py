"""Explicit history HTTP route registration."""

from collections.abc import Callable

from fastapi import APIRouter
from fastapi import status

from spotify_manager.interfaces.http.models.common import LibraryMirrorFilesStatus
from spotify_manager.interfaces.http.models.jobs import BlastJobResult


def router(
    cmd_update_scrobble_history: Callable[..., BlastJobResult],
    library_mirror_files_status: Callable[..., LibraryMirrorFilesStatus],
    cmd_active_scrobble_history_jobs: Callable[..., list[BlastJobResult]],
    cmd_scrobble_history_job: Callable[..., BlastJobResult],
    cmd_cancel_scrobble_history_job: Callable[..., BlastJobResult],
) -> APIRouter:
    """Register the original history endpoints.

    Args:
        cmd_update_scrobble_history: Existing facade handler.
        library_mirror_files_status: Existing facade handler.
        cmd_active_scrobble_history_jobs: Existing facade handler.
        cmd_scrobble_history_job: Existing facade handler.
        cmd_cancel_scrobble_history_job: Existing facade handler.

    Returns:
        An owned router with unchanged paths, methods and response metadata.
    """
    routes = APIRouter()
    routes.add_api_route(
        "/commands/update-scrobble-history",
        cmd_update_scrobble_history,
        methods=["POST"],
        response_model=BlastJobResult,
        status_code=status.HTTP_202_ACCEPTED,
    )
    routes.add_api_route(
        "/library-mirrors/status",
        library_mirror_files_status,
        methods=["GET"],
        response_model=LibraryMirrorFilesStatus,
    )
    routes.add_api_route(
        "/commands/update-scrobble-history-jobs",
        cmd_active_scrobble_history_jobs,
        methods=["GET"],
        response_model=list[BlastJobResult],
    )
    routes.add_api_route(
        "/commands/update-scrobble-history-jobs/{job_id}",
        cmd_scrobble_history_job,
        methods=["GET"],
        response_model=BlastJobResult,
    )
    routes.add_api_route(
        "/commands/update-scrobble-history-jobs/{job_id}/cancel",
        cmd_cancel_scrobble_history_job,
        methods=["POST"],
        response_model=BlastJobResult,
    )
    return routes
