"""Explicit lookups HTTP route registration."""

from collections.abc import Callable

from fastapi import APIRouter

from spotify_manager.interfaces.http.models.common import CommandResult
from spotify_manager.models.lookups import AlbumEvaluation
from spotify_manager.models.lookups import ArtistLibraryStats
from spotify_manager.models.lookups import TrackScrobbleStatus


def router(
    refresh_library: Callable[..., CommandResult],
    artist_stats: Callable[..., ArtistLibraryStats],
    album_evaluation: Callable[..., AlbumEvaluation],
    track_scrobble_status: Callable[..., TrackScrobbleStatus],
) -> APIRouter:
    """Register the original lookups endpoints.

    Args:
        refresh_library: Existing facade handler.
        artist_stats: Existing facade handler.
        album_evaluation: Existing facade handler.
        track_scrobble_status: Existing facade handler.

    Returns:
        An owned router with unchanged paths, methods and response metadata.
    """
    routes = APIRouter()
    routes.add_api_route(
        "/library/refresh",
        refresh_library,
        methods=["POST"],
        response_model=CommandResult,
    )
    routes.add_api_route(
        "/artists/stats",
        artist_stats,
        methods=["GET"],
        response_model=ArtistLibraryStats,
    )
    routes.add_api_route(
        "/albums/evaluation",
        album_evaluation,
        methods=["GET"],
        response_model=AlbumEvaluation,
    )
    routes.add_api_route(
        "/tracks/scrobbles",
        track_scrobble_status,
        methods=["GET"],
        response_model=TrackScrobbleStatus,
    )
    return routes
