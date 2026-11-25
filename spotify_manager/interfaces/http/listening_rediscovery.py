"""Expose the private artist shortlist and selected Spotify album tracklists."""

from typing import Annotated
from typing import Literal
from typing import cast

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Query
from fastapi import Request
from pydantic import BaseModel
from pydantic import Field

from spotify_manager.application.listening_album_tracklists import AlbumPublicationError
from spotify_manager.application.listening_album_tracklists import AlbumTracklistReads
from spotify_manager.application.listening_album_tracklists import RediscoveryTracklists
from spotify_manager.application.listening_album_tracklists import (
    get_rediscovery_tracklists,
)
from spotify_manager.application.listening_rediscovery import get_artist_rediscovery
from spotify_manager.domain.listening_rediscovery import PLAYLIST_ALBUM_LIMIT
from spotify_manager.domain.listening_rediscovery import ArtistRediscovery
from spotify_manager.domain.listening_rediscovery import RediscoveryHorizon
from spotify_manager.domain.listening_rediscovery import RediscoveryRules
from spotify_manager.domain.listening_rediscovery import RediscoveryWindowError
from spotify_manager.infrastructure.listening.library_runtime import LibraryRuntime
from spotify_manager.interfaces.http.listening import IndexDep
from spotify_manager.interfaces.http.listening import LibraryVersion
from spotify_manager.interfaces.http.listening import QueryDep
from spotify_manager.interfaces.http.presenters.listening import ListeningEnvelope
from spotify_manager.interfaces.http.presenters.listening import present_listening


router = APIRouter(prefix="/lastfm/analytics/rediscovery", tags=["Listening Explorer"])
type AlbumURI = Annotated[str, Field(pattern=r"^spotify:album:[A-Za-z0-9]{22}$")]


class AlbumTracklistRequest(BaseModel):
    """Bound a request to one selected album per artist in a short playlist."""

    albums: Annotated[
        tuple[AlbumURI, ...], Field(min_length=1, max_length=PLAYLIST_ALBUM_LIMIT)
    ]


def rediscovery_rules(
    horizon: Literal["30", "90", "365"] = "90",
    history: Literal["year", "selection"] = "year",
    minimum_plays: Annotated[int, Query(ge=1, le=1000000)] = 50,
    minimum_weeks: Annotated[int, Query(ge=1, le=5200)] = 3,
) -> RediscoveryRules:
    """Collect validated historical and recent listening options.

    Args:
        horizon: Trailing recent days in the current published archive.
        history: Prior calendar year duration or explicit historical selection.
        minimum_plays: Minimum historical recorded plays.
        minimum_weeks: Minimum distinct Monday-based historical weeks.

    Returns:
        Applied artist shortlist rules.
    """
    days: dict[str, RediscoveryHorizon] = {"30": 30, "90": 90, "365": 365}
    return RediscoveryRules(
        days[horizon], history == "year", minimum_plays, minimum_weeks
    )


@router.get("/artists")
def listening_rediscovery_artists(
    request: Request,
    index: IndexDep,
    query: QueryDep,
    rules: Annotated[RediscoveryRules, Depends(rediscovery_rules)],
    library_snapshot: Annotated[str | None, Query(pattern=r"^l1-[0-9a-f]{64}$")] = None,
) -> ListeningEnvelope[ArtistRediscovery]:
    """Find past favorites with little or no recent listening and suggest albums.

    Args:
        request: Owner of the independent saved-album publication.
        index: Pinned listening archive.
        query: Explicit historical dates and timezone.
        rules: Historical thresholds and recent horizon.
        library_snapshot: Optional pinned Spotify collection.

    Returns:
        Historical and recent listening evidence, even when albums are unavailable.
    """
    runtime = cast(LibraryRuntime, request.app.state.listening_library)
    catalog = runtime.acquire(library_snapshot) if library_snapshot else None
    try:
        result = get_artist_rediscovery(index, catalog, query, rules)
    except RediscoveryWindowError as error:
        raise HTTPException(422, str(error)) from error
    return present_listening(index, result.dates.historical, result)


@router.post("/album-tracklists")
async def listening_rediscovery_album_tracks(
    request: Request,
    index: IndexDep,
    query: QueryDep,
    library_snapshot: LibraryVersion,
    choices: AlbumTracklistRequest,
) -> ListeningEnvelope[RediscoveryTracklists]:
    """Read the exact Spotify disc and track sequence for selected saved editions.

    Args:
        request: Owner of the saved-album catalog and Spotify tracklist reader.
        index: The same pinned archive used for the shortlist.
        query: Historical dates and timezone for the preview.
        library_snapshot: The same pinned collection used for album selection.
        choices: Selected Spotify album URIs in playlist order.

    Returns:
        Complete or individually unavailable album tracklists in the requested order.
    """
    if len(set(choices.albums)) != len(choices.albums):
        raise HTTPException(422, "Send each selected Spotify album once.")
    catalog = cast(LibraryRuntime, request.app.state.listening_library).acquire(
        library_snapshot
    )
    source = cast(AlbumTracklistReads, request.app.state.listening_album_tracklists)
    try:
        result = await get_rediscovery_tracklists(catalog, choices.albums, source)
    except AlbumPublicationError as error:
        raise HTTPException(422, str(error)) from error
    return present_listening(index, query, result)
