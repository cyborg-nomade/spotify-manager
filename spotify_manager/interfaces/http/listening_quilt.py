"""Declare protected cached album quilts and explicit bounded artwork lookups."""

from datetime import UTC
from datetime import datetime
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

from spotify_manager.application.listening_cover_ports import CoverFetchRequest
from spotify_manager.application.listening_cover_ports import CoverFetchStatus
from spotify_manager.application.listening_cover_ports import CoverSourceError
from spotify_manager.application.listening_covers import ListeningCoverEnrichment
from spotify_manager.application.listening_covers import get_listening_covers
from spotify_manager.application.listening_covers import get_quilt_image
from spotify_manager.application.listening_ports import ListeningVersionError
from spotify_manager.domain.listening_cover_values import CoverCatalog
from spotify_manager.domain.listening_cover_values import ListeningQuilt
from spotify_manager.domain.listening_cover_values import QuiltOptions
from spotify_manager.domain.listening_quilt import cover_fetch_candidates
from spotify_manager.interfaces.http.listening import IndexDep
from spotify_manager.interfaces.http.listening import QueryDep
from spotify_manager.interfaces.http.presenters.listening import ListeningEnvelope
from spotify_manager.interfaces.http.presenters.listening import present_listening


router = APIRouter(prefix="/lastfm/analytics/quilt", tags=["Listening Explorer covers"])


def _enrichment(request: Request) -> ListeningCoverEnrichment:
    return cast(ListeningCoverEnrichment, request.app.state.listening_covers)


def _catalog(request: Request, snapshot: str) -> CoverCatalog:
    try:
        return _enrichment(request).cache.acquire(snapshot)
    except ListeningVersionError as error:
        raise HTTPException(
            409,
            str(error),
            headers={
                "X-Listening-Conflict": "covers",
                "Cache-Control": "private, no-store",
            },
        ) from None


def quilt_options(
    size: Annotated[
        int,
        Query(
            ge=9,
            le=49,
            description="Square tile count: 9, 16, 25 or 49.",
            json_schema_extra={"enum": [9, 16, 25, 49]},
        ),
    ] = 16,
    q: Annotated[str, Query(max_length=100)] = "",
) -> QuiltOptions:
    """Validate bounded quilt dimensions and optional title/artist search.

    Args:
        size: Maximum square tile count.
        q: Album or artist display-name substring.

    Returns:
        Exact applied quilt options.
    """
    if size not in {9, 16, 25, 49}:
        raise HTTPException(422, "Choose 9, 16, 25 or 49 albums.")
    return QuiltOptions(cast(Literal[9, 16, 25, 49], size), q)


type QuiltDep = Annotated[QuiltOptions, Depends(quilt_options)]
type CoverVersion = Annotated[str, Query(pattern=r"^c1-[0-9a-f]{64}$")]


@router.get("/status")
async def listening_cover_status(
    request: Request, response: Response
) -> CoverFetchStatus:
    """Read cache identity and batch progress without external provider calls.

    Args:
        request: Configured named stage owner.
        response: Response receiving private cache policy.

    Returns:
        Explicit lookup lifecycle and a complete independent metadata token.
    """
    response.headers["Cache-Control"] = "private, no-store"
    return _enrichment(request).status()


@router.get("")
def listening_quilt(
    request: Request,
    query: QueryDep,
    index: IndexDep,
    options: QuiltDep,
    metadata_snapshot: CoverVersion,
) -> ListeningEnvelope[ListeningQuilt]:
    """Present a ranked quilt using only pinned historical counts and cached art.

    Args:
        request: Configured cover stage owner.
        query: Validated shared listening selection.
        index: Complete pinned history generation.
        options: Bounded quilt size and search.
        metadata_snapshot: Independent pinned cover generation.

    Returns:
        Exact selected counts, visible albums and explicit artwork outcomes.
    """
    catalog = _catalog(request, metadata_snapshot)
    return present_listening(
        index, query, get_listening_covers(index, catalog, query, options)
    )


@router.get("/images/{album_key}")
def listening_cover_image(
    request: Request,
    album_key: Annotated[str, Path(pattern=r"^[0-9a-f]{64}$")],
    metadata_snapshot: CoverVersion,
) -> Response:
    """Serve only validated local bytes pinned to an authenticated cover generation.

    Args:
        request: Cache resource owner.
        album_key: Original history identity; never an arbitrary external URL.
        metadata_snapshot: Exact cover generation binding metadata and bytes.

    Returns:
        Private JPEG bytes with content sniffing disabled.

    Raises:
        HTTPException: The generation expired or this album has no cached art.
    """
    catalog = _catalog(request, metadata_snapshot)
    image = get_quilt_image(catalog, album_key)
    if image is None:
        raise HTTPException(
            404,
            "No cached cover for this album.",
            headers={"Cache-Control": "private, no-store"},
        )
    return Response(
        image,
        media_type="image/jpeg",
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )


def cover_batch(
    request: Request,
    query: QueryDep,
    index: IndexDep,
    options: QuiltDep,
    limit: Annotated[int, Query(ge=1, le=10)] = 10,
    force: bool = False,
) -> CoverFetchRequest:
    """Capture visible missing/stale album names in FastAPI's sync worker pool.

    Args:
        request: Named cover stage owner.
        query: Validated listening selection.
        index: Pinned complete history resource.
        options: Applied visible quilt size and search.
        limit: Maximum album lookups.
        force: Include recently cached observations.

    Returns:
        Captured batch selected off the event loop, before background work starts.
    """
    stage = _enrichment(request)
    quilt = get_listening_covers(index, stage.cache.current(), query, options)
    albums = cover_fetch_candidates(quilt.items, datetime.now(UTC), limit, force)
    return CoverFetchRequest(albums, index.metadata.snapshot)


@router.post("/refresh")
async def fetch_listening_covers(
    request: Request,
    response: Response,
    batch: Annotated[CoverFetchRequest, Depends(cover_batch)],
) -> CoverFetchStatus:
    """Explicitly start one bounded lookup using names from the displayed quilt.

    Args:
        request: Configured named enrichment stage owner.
        response: Response receiving private cache policy.
        batch: Captured names selected by the synchronous framework dependency.

    Returns:
        Accepted progress or the current batch without duplication.

    Raises:
        HTTPException: Lookup resources are unavailable.
    """
    response.headers["Cache-Control"] = "private, no-store"
    try:
        return _enrichment(request).start(batch)
    except CoverSourceError as error:
        raise HTTPException(503, str(error)) from None


@router.post("/cancel")
async def cancel_listening_covers(
    request: Request, response: Response
) -> CoverFetchStatus:
    """Cancel only cover work while retaining every completed observation/image.

    Args:
        request: Configured named enrichment stage owner.
        response: Response receiving private cache policy.

    Returns:
        Cancellation progress with completed cached artwork retained.
    """
    response.headers["Cache-Control"] = "private, no-store"
    return _enrichment(request).cancel()
