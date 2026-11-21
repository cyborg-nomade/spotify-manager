"""Declare cached tag analytics and explicit bounded metadata lookup actions."""

from datetime import UTC
from datetime import datetime
from typing import Annotated
from typing import Literal
from typing import cast

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Query
from fastapi import Request
from fastapi import Response

from spotify_manager.application.listening_ports import ListeningVersionError
from spotify_manager.application.listening_tag_ports import TagFetchRequest
from spotify_manager.application.listening_tag_ports import TagFetchStatus
from spotify_manager.application.listening_tag_ports import TagSourceError
from spotify_manager.application.listening_tags import ListeningTagEnrichment
from spotify_manager.application.listening_tags import get_listening_tags
from spotify_manager.domain.listening_tag_values import ListeningTags
from spotify_manager.domain.listening_tag_values import TagOptions
from spotify_manager.domain.listening_tags import tag_fetch_candidates
from spotify_manager.interfaces.http.listening import IndexDep
from spotify_manager.interfaces.http.listening import QueryDep
from spotify_manager.interfaces.http.presenters.listening import ListeningEnvelope
from spotify_manager.interfaces.http.presenters.listening import present_listening


router = APIRouter(prefix="/lastfm/analytics/tags", tags=["Listening Explorer tags"])


def _enrichment(request: Request) -> ListeningTagEnrichment:
    return cast(ListeningTagEnrichment, request.app.state.listening_tags)


def tag_options(
    per_artist: Annotated[int, Query(ge=1, le=3)] = 3,
    tag: Annotated[str | None, Query(pattern=r"^(other|unknown|[0-9a-f]{64})$")] = None,
    q: Annotated[str, Query(max_length=100)] = "",
    page: Annotated[int, Query(ge=1, le=100000)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> TagOptions:
    """Validate allocation and bound the supporting artist-evidence page.

    Args:
        per_artist: Leading tag or equal allocation among up to three tags.
        tag: Optional evidence tag or explicit unknown category.
        q: Artist display-name search.
        page: One-based evidence page.
        limit: Maximum returned rows.

    Returns:
        Applied tag-view options with no provider request implied.
    """
    if per_artist not in (1, 3):
        raise HTTPException(422, "Choose one or three tags per artist.")
    return TagOptions(cast(Literal[1, 3], per_artist), tag, q, page, limit)


@router.get("/status")
async def listening_tag_status(request: Request, response: Response) -> TagFetchStatus:
    """Read cache identity and explicit-batch progress without provider calls.

    Args:
        request: Configured named application stage owner.
        response: Response receiving private cache policy.

    Returns:
        Lookup progress and a complete metadata token, even for an empty cache.
    """
    response.headers["Cache-Control"] = "private, no-store"
    return _enrichment(request).status()


@router.get("")
def listening_tags(
    request: Request,
    query: QueryDep,
    index: IndexDep,
    options: Annotated[TagOptions, Depends(tag_options)],
    metadata_snapshot: Annotated[str, Query(pattern=r"^t1-[0-9a-f]{64}$")],
) -> ListeningEnvelope[ListeningTags]:
    """Apply only pinned cached community tags to the selected recorded history.

    Args:
        request: Cache resource owner.
        query: Validated listening selection.
        index: Pinned complete history generation.
        options: Applied allocation and evidence filters.
        metadata_snapshot: Independently pinned cached metadata generation.

    Returns:
        Complete allocations, explicit unknowns and bounded supporting evidence.
    """
    try:
        catalog = _enrichment(request).cache.acquire(metadata_snapshot)
    except ListeningVersionError as error:
        raise HTTPException(
            409, str(error), headers={"X-Listening-Conflict": "tags"}
        ) from None
    return present_listening(
        index, query, get_listening_tags(index, catalog, query, options)
    )


@router.post("/refresh")
async def fetch_listening_tags(
    request: Request,
    response: Response,
    query: QueryDep,
    index: IndexDep,
    limit: Annotated[int, Query(ge=1, le=50)] = 25,
    force: bool = False,
) -> TagFetchStatus:
    """Explicitly request one bounded highest-play missing/stale artist batch.

    Args:
        request: Configured named enrichment application stage.
        response: Response receiving private cache policy.
        query: Listening selection used only to select artist names.
        index: Pinned source for batch selection.
        limit: Maximum public provider requests.
        force: Refresh recently cached observations as well.

    Returns:
        Accepted batch progress or the already-running batch without duplication.

    Raises:
        HTTPException: Provider configuration is unavailable.
    """
    response.headers["Cache-Control"] = "private, no-store"
    stage = _enrichment(request)
    artists = index.lifetimes(query, "artist")
    selected = tag_fetch_candidates(
        artists, stage.cache.current(), datetime.now(UTC), limit, force
    )
    try:
        return stage.start(TagFetchRequest(selected, index.metadata.snapshot))
    except TagSourceError as error:
        raise HTTPException(503, str(error)) from None


@router.post("/cancel")
async def cancel_listening_tags(request: Request, response: Response) -> TagFetchStatus:
    """Cancel only the metadata batch, retaining completed cached observations.

    Args:
        request: Configured named enrichment application stage.
        response: Response receiving private cache policy.

    Returns:
        Cancellation progress without changing canonical data or routine jobs.
    """
    response.headers["Cache-Control"] = "private, no-store"
    return _enrichment(request).cancel()
