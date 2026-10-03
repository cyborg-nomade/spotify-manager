"""Explicit library commands HTTP route registration."""

from collections.abc import Callable

from fastapi import APIRouter

from spotify_manager.interfaces.http.models.common import CommandResult
from spotify_manager.interfaces.http.models.common import CountResult


def router(
    cmd_monthly_routines: Callable[..., CommandResult],
    cmd_update_total_albums: Callable[..., CommandResult],
    cmd_restore_your_library: Callable[..., CommandResult],
    cmd_compare_lib_files: Callable[..., CommandResult],
    cmd_analyse_comp: Callable[..., CommandResult],
    cmd_convert_lib: Callable[..., CommandResult],
    cmd_count_artists: Callable[..., CountResult],
) -> APIRouter:
    """Register the original library commands endpoints.

    Args:
        cmd_monthly_routines: Existing facade handler.
        cmd_update_total_albums: Existing facade handler.
        cmd_restore_your_library: Existing facade handler.
        cmd_compare_lib_files: Existing facade handler.
        cmd_analyse_comp: Existing facade handler.
        cmd_convert_lib: Existing facade handler.
        cmd_count_artists: Existing facade handler.

    Returns:
        An owned router with unchanged paths, methods and response metadata.
    """
    routes = APIRouter()
    routes.add_api_route(
        "/commands/monthly-routines",
        cmd_monthly_routines,
        methods=["POST"],
        response_model=CommandResult,
    )
    routes.add_api_route(
        "/commands/update-total-albums",
        cmd_update_total_albums,
        methods=["POST"],
        response_model=CommandResult,
    )
    routes.add_api_route(
        "/commands/restore-your-library",
        cmd_restore_your_library,
        methods=["POST"],
        response_model=CommandResult,
    )
    routes.add_api_route(
        "/commands/compare-lib-files",
        cmd_compare_lib_files,
        methods=["POST"],
        response_model=CommandResult,
    )
    routes.add_api_route(
        "/commands/analyse-comp",
        cmd_analyse_comp,
        methods=["POST"],
        response_model=CommandResult,
    )
    routes.add_api_route(
        "/commands/convert-lib",
        cmd_convert_lib,
        methods=["POST"],
        response_model=CommandResult,
    )
    routes.add_api_route(
        "/commands/count-artists",
        cmd_count_artists,
        methods=["GET"],
        response_model=CountResult,
    )
    return routes
