"""Expose a private review and confirmation flow for Spotify playlist additions."""

from dataclasses import dataclass
from typing import Annotated
from typing import Literal
from typing import cast

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Path
from fastapi import Query
from fastapi import Request
from fastapi import Response
from pydantic import BaseModel
from pydantic import Field

from spotify_manager.application.listening_album_tracklists import AlbumPublicationError
from spotify_manager.application.listening_album_tracklists import AlbumTracklistReads
from spotify_manager.application.listening_export import PlaylistServiceUnavailableError
from spotify_manager.application.listening_export_plan import ExportSourceError
from spotify_manager.application.listening_export_plan import album_export_tracks
from spotify_manager.application.listening_export_plan import make_export_plan
from spotify_manager.application.listening_export_plan import selection_export_tracks
from spotify_manager.application.listening_playlist import get_playlist_preview
from spotify_manager.application.listening_ports import ListeningNotReadyError
from spotify_manager.application.listening_ports import ListeningVersionError
from spotify_manager.domain.listening_export import ExportSources
from spotify_manager.domain.listening_export import ExportTrack
from spotify_manager.domain.listening_export import PlaylistExportConflictError
from spotify_manager.domain.listening_export import SpotifyDestination
from spotify_manager.domain.listening_library_values import LibraryCatalog
from spotify_manager.infrastructure.listening.library_runtime import LibraryRuntime
from spotify_manager.infrastructure.listening.runtime import ListeningRuntime
from spotify_manager.interfaces.http.listening import IndexDep
from spotify_manager.interfaces.http.listening import LibraryVersion
from spotify_manager.interfaces.http.listening import PlaylistReviewRequest
from spotify_manager.interfaces.http.listening import QueryDep
from spotify_manager.interfaces.http.listening import playlist_reviews
from spotify_manager.interfaces.http.listening_rediscovery import AlbumTracklistRequest
from spotify_manager.interfaces.http.playlist_export_runtime import (
    PlaylistExportRuntime,
)
from spotify_manager.interfaces.http.presenters.listening_export import ExportPage
from spotify_manager.interfaces.http.presenters.listening_export import ExportStatus
from spotify_manager.interfaces.http.presenters.listening_export import export_page
from spotify_manager.interfaces.http.presenters.listening_export import export_status


router = APIRouter(
    prefix="/lastfm/analytics/playlist-export", tags=["Listening Explorer"]
)
type ExportID = Annotated[str, Path(pattern=r"^[a-f0-9]{32}$")]


class NewPlaylist(BaseModel):
    """Choose a named new private playlist."""

    kind: Literal["new"]
    name: Annotated[str, Field(min_length=1, max_length=100)]


class ExistingPlaylist(BaseModel):
    """Choose a Spotify playlist owned by the active account."""

    kind: Literal["existing"]
    identity: Annotated[str, Field(pattern=r"^[A-Za-z0-9]{22}$")]


class HistorySource(PlaylistReviewRequest):
    """Use the first-play proposal with the same current browser reviews."""

    kind: Literal["history"]


class AlbumSource(AlbumTracklistRequest):
    """Use the ordered saved albums from rediscovery."""

    kind: Literal["albums"]


class PreparePlaylistExport(BaseModel):
    """Prepare an exact review from one pinned source and destination."""

    destination: Annotated[NewPlaylist | ExistingPlaylist, Field(discriminator="kind")]
    source: Annotated[HistorySource | AlbumSource, Field(discriminator="kind")]


def _runtime(request: Request, response: Response) -> PlaylistExportRuntime:
    response.headers["Cache-Control"] = "private, no-store"
    return cast(PlaylistExportRuntime, request.app.state.listening_exports)


type ExportsDep = Annotated[PlaylistExportRuntime, Depends(_runtime)]


@dataclass(frozen=True)
class PreparedSource:
    """Keep the request's pinned catalog and resolved chronological tracks."""

    scope: ExportSources
    catalog: LibraryCatalog
    body: PreparePlaylistExport
    tracks: tuple[ExportTrack, ...]


def prepare_export_source(
    request: Request,
    index: IndexDep,
    query: QueryDep,
    library_snapshot: LibraryVersion,
    body: PreparePlaylistExport,
) -> PreparedSource:
    """Pin sources and resolve the local history preview on FastAPI's read thread.

    Args:
        request: Owner of the current collection publication.
        index: Pinned listening archive.
        query: Original history filters.
        library_snapshot: Pinned collection version.
        body: Explicit source and destination choices.

    Returns:
        Pinned input and computed history order for the history mode.
    """
    library = cast(LibraryRuntime, request.app.state.listening_library)
    catalog = library.acquire(library_snapshot)
    scope = ExportSources(index.metadata.snapshot, library_snapshot)
    if isinstance(body.source, AlbumSource):
        return PreparedSource(scope, catalog, body, ())
    try:
        preview = get_playlist_preview(
            index, catalog, query, playlist_reviews(body.source)
        )
        return PreparedSource(scope, catalog, body, selection_export_tracks(preview))
    except PlaylistExportConflictError as error:
        raise HTTPException(409, str(error)) from error


@router.get("/destinations")
async def playlist_export_destinations(
    runtime: ExportsDep,
) -> tuple[SpotifyDestination, ...]:
    """List existing Spotify playlists available for this account's export.

    Args:
        runtime: Process-local preview and background resource owner.

    Returns:
        Playlists owned by the authenticated Spotify account.
    """
    try:
        account = await runtime.spotify.account()
        return await runtime.spotify.destinations(account)
    except PlaylistServiceUnavailableError as error:
        raise HTTPException(503, str(error)) from error


@router.post("/plans")
async def prepare_playlist_export(
    request: Request,
    prepared: Annotated[PreparedSource, Depends(prepare_export_source)],
    runtime: ExportsDep,
) -> ExportPage:
    """Build the exact ordered additions and present them before any Spotify write.

    Args:
        request: Owner of the album-track reader.
        prepared: Validated choices and pinned source evidence.
        runtime: Process-local plan owner.

    Returns:
        Expiring plan, destination and its first page of additions.
    """
    body = prepared.body
    tracks = prepared.tracks
    try:
        if isinstance(body.source, AlbumSource):
            albums = cast(
                AlbumTracklistReads, request.app.state.listening_album_tracklists
            )
            tracks = await album_export_tracks(
                prepared.catalog, body.source.albums, albums
            )
        identity, name = _target_input(body.destination)
        plan = await make_export_plan(
            prepared.scope, tracks, runtime.spotify, identity, name
        )
    except (AlbumPublicationError, ExportSourceError) as error:
        raise HTTPException(422, str(error)) from error
    except PlaylistExportConflictError as error:
        raise HTTPException(409, str(error)) from error
    except PlaylistServiceUnavailableError as error:
        raise HTTPException(503, str(error)) from error
    return export_page(runtime.prepare(plan), 1)


def _target_input(target: NewPlaylist | ExistingPlaylist) -> tuple[str | None, str]:
    if isinstance(target, ExistingPlaylist):
        return target.identity, ""
    return None, target.name.strip()


@router.get("/plans/{identity}")
async def playlist_export_page(
    identity: ExportID, runtime: ExportsDep, page: Annotated[int, Query(ge=1)] = 1
) -> ExportPage:
    """Read one bounded page of the exact additions and latest job status.

    Args:
        identity: Previously prepared job ID.
        runtime: Owner of the confirmed job.
        page: One-based page of additions.

    Returns:
        The job progress and this page of its immutable additions.
    """
    return export_page(runtime.get(identity), page)


@router.post("/plans/{identity}/confirm")
async def confirm_playlist_export(
    request: Request, identity: ExportID, runtime: ExportsDep
) -> ExportStatus:
    """Confirm an exact Spotify export, or resume the same interrupted job.

    Args:
        request: Spotify source owners for the initial version check.
        identity: Previously prepared job ID.
        runtime: Owner of the plan and job reservations.

    Returns:
        Current status for the job that will perform the addition.
    """
    job = runtime.get(identity)
    if job.stage == "prepared":
        _confirm_sources(request, job.plan.scope)
    return export_status(runtime.start(identity))


def _confirm_sources(request: Request, scope: ExportSources) -> None:
    history = cast(ListeningRuntime, request.app.state.listening)
    library = cast(LibraryRuntime, request.app.state.listening_library)
    try:
        with history.acquire(scope.history):
            library.acquire(scope.library)
    except (ListeningNotReadyError, ListeningVersionError) as error:
        raise HTTPException(
            409, "A publication expired. Reopen the preview before exporting."
        ) from error


@router.post("/plans/{identity}/pause")
async def pause_playlist_export(
    identity: ExportID, runtime: ExportsDep
) -> ExportStatus:
    """Stop the confirmed job after observing the current batch.

    Args:
        identity: Previously confirmed job ID.
        runtime: Owner of the job and safe stop signal.

    Returns:
        Current status, including verified additions already made.
    """
    return export_status(runtime.pause(identity))
