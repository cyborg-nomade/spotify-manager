"""Declare protected inferred-session reads over a pinned history generation."""

from typing import Annotated
from typing import Literal

from fastapi import APIRouter
from fastapi import Depends
from fastapi import Path
from fastapi import Query

from spotify_manager.application.listening_sessions import get_listening_session_records
from spotify_manager.application.listening_sessions import get_listening_sessions
from spotify_manager.domain.listening_session_values import ListeningSessionDetail
from spotify_manager.domain.listening_session_values import ListeningSessions
from spotify_manager.domain.listening_session_values import SessionOptions
from spotify_manager.domain.listening_session_values import SessionSelection
from spotify_manager.domain.listening_values import RecordOptions
from spotify_manager.interfaces.http.listening import IndexDep
from spotify_manager.interfaces.http.listening import QueryDep
from spotify_manager.interfaces.http.presenters.listening import ListeningEnvelope
from spotify_manager.interfaces.http.presenters.listening import present_listening


router = APIRouter(
    prefix="/lastfm/analytics/sessions", tags=["Listening Explorer sessions"]
)
type Gap = Annotated[int, Query(ge=1, le=240)]


def session_options(
    gap_minutes: Gap = 30,
    minimum_plays: Annotated[int, Query(ge=1, le=100000000)] = 1,
    order: Literal["recent", "plays"] = "recent",
    page: Annotated[int, Query(ge=1, le=100000)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> SessionOptions:
    """Validate explicit inference rules and bounded session pagination.

    Args:
        gap_minutes: A strictly larger adjacent UTC gap starts a new group.
        minimum_plays: Inclusive minimum rows per group, applied after grouping.
        order: Most recent or largest groups first.
        page: One-based group page.
        limit: Maximum returned groups.

    Returns:
        Exact applied group and presentation options.
    """
    return SessionOptions(gap_minutes, minimum_plays, order, page, limit)


@router.get("")
def listening_sessions(
    query: QueryDep,
    index: IndexDep,
    options: Annotated[SessionOptions, Depends(session_options)],
) -> ListeningEnvelope[ListeningSessions]:
    """Present inferred groups using only the shared selection's recorded rows.

    Args:
        query: Exact dates, timezone and optional artist/rhythm filters.
        index: Complete pinned history generation.
        options: Explicit recorded-gap rule and bounded group page.

    Returns:
        Reconciled selected and matching totals, trends, sizes and a group page.
    """
    return present_listening(
        index, query, get_listening_sessions(index, query, options)
    )


@router.get("/{first_ms}/records")
def listening_session_records(
    first_ms: Annotated[int, Path(ge=0, le=4102444799999)],
    query: QueryDep,
    index: IndexDep,
    gap_minutes: Gap = 30,
    page: Annotated[int, Query(ge=1, le=100000)] = 1,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> ListeningEnvelope[ListeningSessionDetail]:
    """Open original rows only when the identifier starts an inferred group.

    Args:
        first_ms: First selected recorded timestamp identifying this group.
        query: The same shared selection used for grouping.
        index: Pinned immutable history generation.
        gap_minutes: The same strictly greater UTC-gap split threshold.
        page: One-based chronological record page.
        limit: At most 200 original rows.

    Returns:
        Exact group and source records, preserving duplicates and timestamp ties.
    """
    selection = SessionSelection(first_ms, gap_minutes)
    result = get_listening_session_records(
        index, query, selection, RecordOptions(page, limit)
    )
    return present_listening(index, query, result)
