"""Explicit state HTTP route registration."""

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter
from fastapi.responses import Response

from spotify_manager.interfaces.http.models.state import SharedStateSnapshot
from spotify_manager.interfaces.http.models.state import SharedStateSummary


def router(
    shared_state_summary: Callable[..., SharedStateSummary],
    shared_state: Callable[..., SharedStateSnapshot],
    shared_state_editor_schema: Callable[..., dict[str, Any]],
    replace_shared_state_namespace: Callable[..., SharedStateSnapshot],
    replace_shared_state: Callable[..., SharedStateSnapshot],
    export_shared_state: Callable[..., Response],
) -> APIRouter:
    """Register the original state endpoints.

    Args:
        shared_state_summary: Existing facade handler.
        shared_state: Existing facade handler.
        shared_state_editor_schema: Existing facade handler.
        replace_shared_state_namespace: Existing facade handler.
        replace_shared_state: Existing facade handler.
        export_shared_state: Existing facade handler.

    Returns:
        An owned router with unchanged paths, methods and response metadata.
    """
    routes = APIRouter()
    routes.add_api_route(
        "/state/summary",
        shared_state_summary,
        methods=["GET"],
        response_model=SharedStateSummary,
    )
    routes.add_api_route(
        "/state", shared_state, methods=["GET"], response_model=SharedStateSnapshot
    )
    routes.add_api_route("/state/schema", shared_state_editor_schema, methods=["GET"])
    routes.add_api_route(
        "/state/namespaces/{namespace}",
        replace_shared_state_namespace,
        methods=["PUT"],
        response_model=SharedStateSnapshot,
    )
    routes.add_api_route(
        "/state",
        replace_shared_state,
        methods=["PUT"],
        response_model=SharedStateSnapshot,
    )
    routes.add_api_route("/state/export", export_shared_state, methods=["GET"])
    return routes
