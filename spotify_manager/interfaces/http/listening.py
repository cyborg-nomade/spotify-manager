"""Declare navigable read-only Listening Explorer endpoints and dependencies."""

import sqlite3
from collections.abc import Iterator
from datetime import date
from typing import Annotated
from typing import Literal
from typing import cast
from zoneinfo import ZoneInfo
from zoneinfo import ZoneInfoNotFoundError

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Path
from fastapi import Query
from fastapi import Request
from fastapi import Response

from spotify_manager.application.listening import get_listening_activity
from spotify_manager.application.listening import get_listening_anniversaries
from spotify_manager.application.listening import get_listening_comparison
from spotify_manager.application.listening import get_listening_discoveries
from spotify_manager.application.listening import get_listening_entity
from spotify_manager.application.listening import get_listening_eras
from spotify_manager.application.listening import get_listening_evolution
from spotify_manager.application.listening import get_listening_overview
from spotify_manager.application.listening import get_listening_rankings
from spotify_manager.application.listening import get_listening_records
from spotify_manager.application.listening import get_listening_rediscovery
from spotify_manager.application.listening_library import get_library_candidates
from spotify_manager.application.listening_library import get_listening_library
from spotify_manager.application.listening_ports import ListeningEntityError
from spotify_manager.application.listening_ports import ListeningNotReadyError
from spotify_manager.application.listening_ports import ListeningStatus
from spotify_manager.application.listening_ports import ListeningVersionError
from spotify_manager.application.listening_scrobble_map import get_scrobble_map
from spotify_manager.domain.listening_capsule_values import ListeningAnniversaries
from spotify_manager.domain.listening_capsule_values import ListeningEras
from spotify_manager.domain.listening_library_values import LibraryCandidateOptions
from spotify_manager.domain.listening_library_values import LibraryCandidatePage
from spotify_manager.domain.listening_library_values import LibraryComparison
from spotify_manager.domain.listening_library_values import LibraryMatch
from spotify_manager.domain.listening_library_values import LibraryOptions
from spotify_manager.domain.listening_scrobble_map import ListeningScrobbleMap
from spotify_manager.domain.listening_values import EntityKind
from spotify_manager.domain.listening_values import EntitySelection
from spotify_manager.domain.listening_values import ListeningActivity
from spotify_manager.domain.listening_values import ListeningComparison
from spotify_manager.domain.listening_values import ListeningDiscoveries
from spotify_manager.domain.listening_values import ListeningEntity
from spotify_manager.domain.listening_values import ListeningEvolution
from spotify_manager.domain.listening_values import ListeningOverview
from spotify_manager.domain.listening_values import ListeningQuery
from spotify_manager.domain.listening_values import ListeningRanking
from spotify_manager.domain.listening_values import ListeningRecords
from spotify_manager.domain.listening_values import ListeningRediscovery
from spotify_manager.domain.listening_values import RankingOptions
from spotify_manager.domain.listening_values import RecordOptions
from spotify_manager.domain.listening_values import RediscoveryOptions
from spotify_manager.infrastructure.listening.library_runtime import LibraryRuntime
from spotify_manager.infrastructure.listening.library_runtime import LibraryStatus
from spotify_manager.infrastructure.listening.reader import ListeningIndex
from spotify_manager.infrastructure.listening.runtime import ListeningRuntime
from spotify_manager.interfaces.http.presenters.listening import ListeningEnvelope
from spotify_manager.interfaces.http.presenters.listening import present_listening


router = APIRouter(prefix="/lastfm/analytics", tags=["Listening Explorer"])
_KEY = r"^[0-9a-f]{64}$"
_SNAPSHOT = r"^v1-[0-9a-f]{64}$"


@router.get("/library/status")
async def listening_library_status(
    request: Request, response: Response, refresh: bool = False
) -> LibraryStatus:
    """Report collection coverage independently of recorded-history readiness.

    Args:
        request: Owner of the configured collection runtime.
        response: Response receiving the private cache policy.
        refresh: Request a new publication check without duplicate workers.

    Returns:
        Current collection token, publication coverage and recovery information.
    """
    response.headers["Cache-Control"] = "private, no-store"
    runtime = cast(LibraryRuntime, request.app.state.listening_library)
    return runtime.status(refresh=refresh)


def library_options(
    kind: EntityKind = "album",
    status: LibraryMatch | Literal["all"] = "all",
    minimum_plays: Annotated[int, Query(ge=1, le=100000000)] = 1,
    q: Annotated[str, Query(max_length=100)] = "",
    page: Annotated[int, Query(ge=1, le=100000)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> LibraryOptions:
    """Collect bounded current-collection comparison values.

    Args:
        kind: Followed artists, saved albums or liked tracks.
        status: Evidence category or all categories.
        minimum_plays: Inclusive selected-play threshold.
        q: Search in original entity and artist names.
        page: One-based result page.
        limit: Maximum returned rows.

    Returns:
        Explicit comparison and pagination options.
    """
    return LibraryOptions(kind, status, minimum_plays, q, page, limit)


def _runtime(request: Request) -> ListeningRuntime:
    return cast(ListeningRuntime, request.app.state.listening)


def listening_query(
    start: Annotated[date, Query(alias="from")],
    end: Annotated[date, Query(alias="to")],
    tz: Annotated[str, Query(max_length=100)] = "Europe/Berlin",
    artist: Annotated[str | None, Query(pattern=_KEY)] = None,
    weekday: Annotated[int | None, Query(ge=0, le=6)] = None,
    hour: Annotated[int | None, Query(ge=0, le=23)] = None,
) -> ListeningQuery:
    """Validate calendar and timezone inputs at the HTTP boundary.

    Args:
        start: Inclusive local first date.
        end: Inclusive local last date.
        tz: IANA timezone.
        artist: Optional artist identity key.
        weekday: Optional Monday-based weekday.
        hour: Optional local hour.

    Returns:
        Typed domain selection.

    Raises:
        HTTPException: Unsupported timezone or invalid date range.
    """
    if start > end or start.year < 1900 or end.year > 2099:
        raise HTTPException(422, "Choose ordered dates between 1900 and 2099.")
    if (end - start).days > 36600:
        raise HTTPException(422, "Choose a range of at most 100 years.")
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise HTTPException(422, "Choose a valid IANA timezone.") from exc
    return ListeningQuery(start, end, tz, artist, weekday, hour)


def listening_index(
    request: Request,
    response: Response,
    snapshot: Annotated[str, Query(pattern=_SNAPSHOT)],
) -> Iterator[ListeningIndex]:
    """Pin one source version and translate expected read-resource failures.

    Args:
        request: Request owning the configured runtime.
        response: Response receiving private cache controls.
        snapshot: Version token obtained from status.

    Yields:
        Ready immutable history resource.

    Raises:
        HTTPException: Source not ready, expired version, unknown entity, or read error.
    """
    response.headers["Cache-Control"] = "private, no-store"
    try:
        with _runtime(request).acquire(snapshot) as index:
            yield index
    except ListeningNotReadyError as exc:
        raise HTTPException(503, str(exc), headers={"Retry-After": "2"}) from exc
    except ListeningVersionError as exc:
        raise HTTPException(409, str(exc)) from exc
    except ListeningEntityError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (OSError, sqlite3.Error) as exc:
        raise HTTPException(
            503, "Recorded history could not be read. Reload shortly."
        ) from exc


def ranking_options(
    kind: EntityKind = "artist",
    q: Annotated[str, Query(max_length=100)] = "",
    page: Annotated[int, Query(ge=1, le=100000)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    order: Literal["plays", "name"] = "plays",
) -> RankingOptions:
    """Collect bounded ranking values into a typed request.

    Args:
        kind: Artist, album, or track.
        q: Unicode-aware substring search.
        page: One-based page.
        limit: Maximum returned rows.
        order: Count or display-name order.

    Returns:
        Explicit ranking and pagination options.
    """
    return RankingOptions(kind, q.strip(), page, limit, order)


type QueryDep = Annotated[ListeningQuery, Depends(listening_query)]
type IndexDep = Annotated[ListeningIndex, Depends(listening_index)]
type RankingDep = Annotated[RankingOptions, Depends(ranking_options)]


def library_candidate_options(
    kind: EntityKind,
    key: Annotated[str, Query(pattern=_KEY)],
    q: Annotated[str, Query(max_length=180)] = "",
    page: Annotated[int, Query(ge=1, le=100000)] = 1,
    limit: Annotated[int, Query(ge=1, le=25)] = 12,
) -> LibraryCandidateOptions:
    """Validate an explicit history identity and bounded mirror search.

    Args:
        kind: Followed artist, saved album, or liked track.
        key: Verified analytics identity selected in Library Bridge.
        q: Candidate title, credit, or exact Spotify URI.
        page: One-based candidate page.
        limit: Maximum candidates returned in this request.

    Returns:
        Typed selection and candidate pagination.
    """
    return LibraryCandidateOptions(EntitySelection(kind, key), q, page, limit)


@router.get("/library")
def listening_library(
    request: Request,
    query: QueryDep,
    index: IndexDep,
    options: Annotated[LibraryOptions, Depends(library_options)],
    library_snapshot: Annotated[str, Query(pattern=r"^l1-[0-9a-f]{64}$")],
) -> ListeningEnvelope[LibraryComparison]:
    """Compare pinned history and collection publications with explicit evidence.

    Args:
        request: Configured collection generation owner.
        query: Validated listening selection, separate from collection dates.
        index: Pinned complete history generation.
        options: Collection, evidence/search filters and bounded pagination.
        library_snapshot: Explicit independently pinned collection generation.

    Returns:
        Evidence, coverage and both publication identities.
    """
    runtime = cast(LibraryRuntime, request.app.state.listening_library)
    catalog = runtime.acquire(library_snapshot)
    result = get_listening_library(index, catalog, query, options)
    return present_listening(index, query, result)


@router.get("/library/candidates")
def listening_library_candidates(
    request: Request,
    query: QueryDep,
    index: IndexDep,
    options: Annotated[LibraryCandidateOptions, Depends(library_candidate_options)],
    library_snapshot: Annotated[str, Query(pattern=r"^l1-[0-9a-f]{64}$")],
) -> ListeningEnvelope[LibraryCandidatePage]:
    """Browse candidate names and credits in the pinned Spotify publication.

    Args:
        request: Configured collection generation owner.
        query: Current history selection and analysis cutoff.
        index: Pinned complete history generation.
        options: Original identity and bounded candidate search.
        library_snapshot: Pinned collection generation.

    Returns:
        Original history evidence, source, and published Spotify identities.
    """
    runtime = cast(LibraryRuntime, request.app.state.listening_library)
    catalog = runtime.acquire(library_snapshot)
    return present_listening(
        index, query, get_library_candidates(index, catalog, query, options)
    )


@router.get("/status")
async def listening_status(
    request: Request, response: Response, refresh: bool = False
) -> ListeningStatus:
    """Return ready coverage while lazily refreshing the published source identity.

    Args:
        request: Runtime-owning request.
        response: Response receiving private cache controls.
        refresh: Check now, reusing any already-running worker.

    Returns:
        Complete index coverage, build progress, or a recoverable source error.
    """
    response.headers["Cache-Control"] = "private, no-store"
    return _runtime(request).status(refresh=refresh)


@router.get("/overview")
def listening_overview(
    query: QueryDep, index: IndexDep
) -> ListeningEnvelope[ListeningOverview]:
    """Return exact counts and calendar-day versus active-day averages.

    Args:
        query: Effective shared selection.
        index: Pinned source generation.

    Returns:
        Versioned listening overview.
    """
    result = get_listening_overview(index, query)
    return present_listening(index, query, result)


@router.get("/activity")
def listening_activity(
    query: QueryDep, index: IndexDep
) -> ListeningEnvelope[ListeningActivity]:
    """Return daily coverage and explicit weekday/hour denominators.

    Args:
        query: Effective shared selection.
        index: Pinned source generation.

    Returns:
        Versioned calendar and rhythm cells.
    """
    result = get_listening_activity(index, query)
    return present_listening(index, query, result)


@router.get("/scrobble-map")
def listening_scrobble_map(
    query: QueryDep, index: IndexDep
) -> ListeningEnvelope[ListeningScrobbleMap]:
    """Return exact counts by calendar period and local wall-clock hour.

    Args:
        query: Effective date, timezone and artist or rhythm selection.
        index: Pinned published history generation.

    Returns:
        The selected period axis, populated cells and source coverage.
    """
    return present_listening(index, query, get_scrobble_map(index, query))


@router.get("/rankings")
def listening_rankings(
    query: QueryDep, index: IndexDep, options: RankingDep
) -> ListeningEnvelope[ListeningRanking]:
    """Return a searchable, bounded artist/album/track ranking.

    Args:
        query: Effective shared selection.
        index: Pinned source generation.
        options: Dimension, name search, ordering, and pagination.

    Returns:
        Versioned ranked entities.
    """
    result = get_listening_rankings(index, query, options)
    return present_listening(index, query, result)


@router.get("/evolution")
def listening_evolution(
    query: QueryDep,
    index: IndexDep,
    grain: Literal["week", "month"] = "month",
) -> ListeningEnvelope[ListeningEvolution]:
    """Return fixed artist series and temporal breadth/concentration metrics.

    Args:
        query: Effective shared selection.
        index: Pinned source generation.
        grain: Monday-based week or calendar month.

    Returns:
        Versioned top-eight-plus-Other series.
    """
    result = get_listening_evolution(index, query, grain)
    return present_listening(index, query, result)


@router.get("/entities/{kind}/{key}")
def listening_entity(
    kind: EntityKind,
    key: Annotated[str, Path(pattern=_KEY)],
    query: QueryDep,
    index: IndexDep,
) -> ListeningEnvelope[ListeningEntity]:
    """Return separate lifetime and selected-period entity facts.

    Args:
        kind: Entity dimension.
        key: Opaque analytics identity.
        query: Effective shared selection.
        index: Pinned source generation.

    Returns:
        Versioned entity facts, activity, related tracks, and first record page.
    """
    result = get_listening_entity(index, query, EntitySelection(kind, key))
    return present_listening(index, query, result)


@router.get("/scrobbles")
def listening_scrobbles(
    query: QueryDep,
    index: IndexDep,
    page: Annotated[int, Query(ge=1, le=100000)] = 1,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    kind: EntityKind | None = None,
    key: Annotated[str | None, Query(pattern=_KEY)] = None,
) -> ListeningEnvelope[ListeningRecords]:
    """Return original recorded names in a bounded newest-first page.

    Args:
        query: Effective shared selection.
        index: Pinned source generation.
        page: One-based record page.
        limit: At most 200 observations.
        kind: Optional selected entity dimension.
        key: Optional selected entity key, required with kind.

    Returns:
        Versioned source records.

    Raises:
        HTTPException: Only one entity-selection component was supplied.
    """
    if (kind is None) != (key is None):
        raise HTTPException(422, "Supply both entity kind and key.")
    selection = (
        EntitySelection(kind, key) if kind is not None and key is not None else None
    )
    result = get_listening_records(
        index, query, RecordOptions(page=page, limit=limit, selection=selection)
    )
    return present_listening(index, query, result)


def _require_full_days(query: ListeningQuery) -> None:
    if query.weekday is not None or query.hour is not None:
        raise HTTPException(
            422, "Discovery and rediscovery use full days. Clear rhythm filters."
        )


@router.get("/discovery")
def listening_discovery(
    query: QueryDep, index: IndexDep
) -> ListeningEnvelope[ListeningDiscoveries]:
    """Return first-observed artist cohorts with incomplete windows identified.

    Args:
        query: Cohort dates, timezone, and optional artist selection.
        index: Pinned source generation.

    Returns:
        Versioned cohort and retention counts.

    Raises:
        HTTPException: Rhythm filters would change first-observed semantics.
    """
    _require_full_days(query)
    result = get_listening_discoveries(index, query)
    return present_listening(index, query, result)


@router.get("/rediscovery")
def listening_rediscovery(
    query: QueryDep,
    index: IndexDep,
    kind: EntityKind = "artist",
    minimum_plays: Annotated[int, Query(ge=1, le=10000000)] = 50,
    minimum_gap: Annotated[int, Query(ge=0, le=36600)] = 365,
) -> ListeningEnvelope[ListeningRediscovery]:
    """Return historical counts and gaps as of the selected analysis end date.

    Args:
        query: Analysis cutoff, timezone, and optional artist.
        index: Pinned source generation.
        kind: Artist, album, or track dimension.
        minimum_plays: Inclusive recorded-play threshold.
        minimum_gap: Inclusive calendar-day inactivity threshold.

    Returns:
        At most 100 versioned forgotten favorites.

    Raises:
        HTTPException: A partial-day rhythm filter was supplied.
    """
    _require_full_days(query)
    result = get_listening_rediscovery(
        index, query, RediscoveryOptions(kind, minimum_plays, minimum_gap)
    )
    return present_listening(index, query, result)


@router.get("/comparison")
def listening_comparison(
    query: QueryDep, index: IndexDep
) -> ListeningEnvelope[ListeningComparison]:
    """Compare artist shares against an equally long preceding calendar period.

    Args:
        query: Effective current selection.
        index: Pinned source generation.

    Returns:
        Versioned current/previous counts, shares, and coverage status.
    """
    result = get_listening_comparison(index, query)
    return present_listening(index, query, result)


@router.get("/eras")
def listening_era_similarity(
    query: QueryDep, index: IndexDep
) -> ListeningEnvelope[ListeningEras]:
    """Compare calendar periods using weighted Jaccard over all artist shares.

    Args:
        query: Effective shared selection.
        index: Pinned source generation.

    Returns:
        Versioned symmetric matrix with undefined empty comparisons.
    """
    result = get_listening_eras(index, query)
    return present_listening(index, query, result)


@router.get("/on-this-day")
def listening_on_this_day(
    query: QueryDep, index: IndexDep
) -> ListeningEnvelope[ListeningAnniversaries]:
    """Return earlier anniversaries of the selected analysis end date.

    Args:
        query: End date, timezone and optional artist; start is ignored.
        index: Pinned source generation.

    Returns:
        Versioned earlier-year days with coverage and leading artists.

    Raises:
        HTTPException: A rhythm filter would conceal calendar anniversaries.
    """
    if query.weekday is not None or query.hour is not None:
        raise HTTPException(422, "On This Day uses full days. Clear rhythm filters.")
    result = get_listening_anniversaries(index, query)
    return present_listening(index, query, result)
