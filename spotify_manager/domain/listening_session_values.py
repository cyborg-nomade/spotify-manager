"""Explicit recorded-gap groups without an assertion of playback duration."""

from dataclasses import dataclass
from typing import Literal

from spotify_manager.domain.listening_values import ListeningRecords
from spotify_manager.domain.listening_values import RankedEntity


@dataclass(frozen=True)
class SessionOptions:
    """Select a gap, minimum size and bounded session page.

    Args:
        gap_minutes: A strictly larger adjacent gap starts a new group.
        minimum_plays: Inclusive minimum recorded rows per group.
        order: Most recent first, or largest groups first.
        page: One-based group page.
        limit: Maximum returned groups.
    """

    gap_minutes: int = 30
    minimum_plays: int = 1
    order: Literal["recent", "plays"] = "recent"
    page: int = 1
    limit: int = 25


@dataclass(frozen=True)
class SessionWindow:
    """Identify a group within its exact history, filters and gap definition.

    Args:
        first_ms: First recorded timestamp and context-dependent group identifier.
        last_ms: Last recorded timestamp, inclusive.
    """

    first_ms: int
    last_ms: int


@dataclass(frozen=True)
class SessionSelection:
    """Select one group within a pinned history and shared filter context.

    Args:
        first_ms: First recorded timestamp identifying the group.
        gap_minutes: Adjacent UTC-gap threshold used to form this group.
    """

    first_ms: int
    gap_minutes: int = 30


@dataclass(frozen=True)
class ListeningSession:
    """Summarize consecutive selected records separated by bounded UTC gaps.

    Args:
        window: First and last recorded timestamps, not playback boundaries.
        plays: Recorded rows, including timestamp ties and duplicates.
        artists: Distinct analytics artist identities.
        tracks: Distinct artist-qualified track identities.
        leading_artist: Most frequent artist, with first-observed tie breaking.
        selection_first: First group in this selection; earlier context is absent.
        selection_last: Last group in this selection; later context is absent.
    """

    window: SessionWindow
    plays: int
    artists: int
    tracks: int
    leading_artist: RankedEntity
    selection_first: bool = False
    selection_last: bool = False


@dataclass(frozen=True)
class SessionSummary:
    """Reconcile complete selected rows and groups surviving the size filter.

    Args:
        selected_plays: All records matching the shared selection.
        selected_sessions: All inferred groups before the minimum-size filter.
        matching_plays: Records in groups meeting the minimum size.
        matching_sessions: Groups meeting the minimum size before pagination.
        median_plays: Median rows per matching group, or zero.
        median_span_ms: Median first-to-last timestamp span, or zero.
    """

    selected_plays: int
    selected_sessions: int
    matching_plays: int
    matching_sessions: int
    median_plays: float
    median_span_ms: float


@dataclass(frozen=True)
class SessionBucket:
    """Count matching groups by the first selected record's local week or month.

    Args:
        label: Monday ISO date or ISO month, including empty buckets.
        sessions: Number of matching groups beginning in this bucket.
        plays: Complete selected rows belonging to those groups.
    """

    label: str
    sessions: int
    plays: int


@dataclass(frozen=True)
class SessionSize:
    """Keep exact group and record totals for one disjoint size band.

    Args:
        label: Inclusive recorded-row size band.
        sessions: Number of matching groups in this band.
        plays: Selected recorded rows belonging to these groups.
    """

    label: str
    sessions: int
    plays: int


@dataclass(frozen=True)
class ListeningSessions:
    """Present bounded groups with complete coverage and chart alternatives.

    Args:
        items: One explicitly ordered group page.
        summary: Full selection and minimum-size coverage.
        options: Exact applied grouping and page options.
        grain: Monday-based week or calendar month for session starts.
        buckets: Complete matching start buckets independent of pagination.
        sizes: Disjoint size bands independent of pagination.
    """

    items: tuple[ListeningSession, ...]
    summary: SessionSummary
    options: SessionOptions
    grain: Literal["week", "month"]
    buckets: tuple[SessionBucket, ...]
    sizes: tuple[SessionSize, ...]


@dataclass(frozen=True)
class ListeningSessionDetail:
    """Keep one inferred group's definition beside its original recorded rows.

    Args:
        session: Exact group within the pinned selection and gap threshold.
        gap_minutes: Applied adjacent UTC-gap threshold.
        records: Bounded chronological source rows with stable source-order ties.
    """

    session: ListeningSession
    gap_minutes: int
    records: ListeningRecords
