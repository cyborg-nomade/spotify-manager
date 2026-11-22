"""Declare cached country analytics and explicit bounded metadata lookup actions."""

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

from spotify_manager.application.listening_origin_ports import OriginFetchRequest
from spotify_manager.application.listening_origin_ports import OriginFetchStatus
from spotify_manager.application.listening_origin_ports import OriginSourceError
from spotify_manager.application.listening_origins import ListeningOriginEnrichment
from spotify_manager.application.listening_origins import get_listening_origins
from spotify_manager.application.listening_ports import ListeningVersionError
from spotify_manager.domain.listening_origin_values import ListeningOrigins
from spotify_manager.domain.listening_origin_values import OriginEvidence
from spotify_manager.domain.listening_origin_values import OriginOptions
from spotify_manager.domain.listening_origins import origin_fetch_candidates
from spotify_manager.interfaces.http.listening import IndexDep
from spotify_manager.interfaces.http.listening import QueryDep
from spotify_manager.interfaces.http.presenters.listening import ListeningEnvelope
from spotify_manager.interfaces.http.presenters.listening import present_listening


router = APIRouter(
    prefix="/lastfm/analytics/origins", tags=["Listening Explorer countries"]
)


def _enrichment(request: Request) -> ListeningOriginEnrichment:
    return cast(ListeningOriginEnrichment, request.app.state.listening_origins)


def origin_options(
    country: Annotated[str | None, Query(pattern=r"^[A-Z]{2}$")] = None,
    evidence: OriginEvidence | Literal["all"] = "all",
    q: Annotated[str, Query(max_length=100)] = "",
    page: Annotated[int, Query(ge=1, le=100000)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> OriginOptions:
    """Validate bounded country and evidence options without provider activity.

    Args:
        country: Optional original country code, including small/historical areas.
        evidence: Evidence outcome, or all artists.
        q: Artist display-name substring.
        page: One-based supporting artist page.
        limit: Maximum evidence rows.

    Returns:
        The exact options applied to supporting evidence.
    """
    return OriginOptions(country, evidence, q, page, limit)


@router.get("/status")
async def listening_origin_status(
    request: Request, response: Response
) -> OriginFetchStatus:
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
def listening_origins(
    request: Request,
    query: QueryDep,
    index: IndexDep,
    options: Annotated[OriginOptions, Depends(origin_options)],
    metadata_snapshot: Annotated[str, Query(pattern=r"^o1-[0-9a-f]{64}$")],
) -> ListeningEnvelope[ListeningOrigins]:
    """Apply only pinned cached country associations to the selected recorded history.

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
            409, str(error), headers={"X-Listening-Conflict": "origins"}
        ) from None
    return present_listening(
        index, query, get_listening_origins(index, catalog, query, options)
    )


@router.post("/refresh")
async def fetch_listening_origins(
    request: Request,
    response: Response,
    query: QueryDep,
    index: IndexDep,
    limit: Annotated[int, Query(ge=1, le=25)] = 25,
    force: bool = False,
) -> OriginFetchStatus:
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
    selected = origin_fetch_candidates(
        artists, stage.cache.current(), datetime.now(UTC), limit, force
    )
    try:
        return stage.start(OriginFetchRequest(selected, index.metadata.snapshot))
    except OriginSourceError as error:
        raise HTTPException(503, str(error)) from None


@router.post("/cancel")
async def cancel_listening_origins(
    request: Request, response: Response
) -> OriginFetchStatus:
    """Cancel only the metadata batch, retaining completed cached observations.

    Args:
        request: Configured named enrichment application stage.
        response: Response receiving private cache policy.

    Returns:
        Cancellation progress without changing canonical data or routine jobs.
    """
    response.headers["Cache-Control"] = "private, no-store"
    return _enrichment(request).cancel()
