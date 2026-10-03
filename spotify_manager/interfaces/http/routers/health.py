"""Explicit health HTTP route registration."""

from collections.abc import Callable

from fastapi import APIRouter


def router(
    health: Callable[..., dict[str, str]],
    auth_check: Callable[..., dict[str, str]],
) -> APIRouter:
    """Register the original health endpoints.

    Args:
        health: Existing facade handler.
        auth_check: Existing facade handler.

    Returns:
        An owned router with unchanged paths, methods and response metadata.
    """
    routes = APIRouter()
    routes.add_api_route("/health", health, methods=["GET"])
    routes.add_api_route("/auth/check", auth_check, methods=["GET"])
    return routes
