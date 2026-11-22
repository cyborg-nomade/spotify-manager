"""Named session exploration over the immutable published-history resource."""

from functools import lru_cache

from spotify_manager.application.listening_ports import ListeningEntityError
from spotify_manager.application.listening_session_ports import ListeningSessionReads
from spotify_manager.domain.listening_session_values import ListeningSession
from spotify_manager.domain.listening_session_values import ListeningSessionDetail
from spotify_manager.domain.listening_session_values import ListeningSessions
from spotify_manager.domain.listening_session_values import SessionOptions
from spotify_manager.domain.listening_session_values import SessionSelection
from spotify_manager.domain.listening_sessions import group_listening_sessions
from spotify_manager.domain.listening_sessions import listening_sessions
from spotify_manager.domain.listening_values import ListeningQuery
from spotify_manager.domain.listening_values import RecordOptions


@lru_cache(maxsize=4)
def _groups(
    index: ListeningSessionReads, query: ListeningQuery, gap_minutes: int
) -> tuple[ListeningSession, ...]:
    return group_listening_sessions(index.artist_plays(query), gap_minutes)


@lru_cache(maxsize=8)
def get_listening_sessions(
    index: ListeningSessionReads, query: ListeningQuery, options: SessionOptions
) -> ListeningSessions:
    """Explore complete selected-record groups without external music lookups.

    Args:
        index: One complete pinned history generation.
        query: Exact shared date, timezone and artist/rhythm selection.
        options: Explicit gap, minimum group size, order and bounded page.

    Returns:
        Bounded groups and full matching chart/coverage totals.
    """
    return listening_sessions(
        _groups(index, query, options.gap_minutes), query, options
    )


def _find_group(
    groups: tuple[ListeningSession, ...], first_ms: int
) -> ListeningSession:
    for group in groups:
        if group.window.first_ms == first_ms:
            return group
    raise ListeningEntityError(
        "This session is absent from the selected records and gap. "
        "Reload the session list."
    )


def get_listening_session_records(
    index: ListeningSessionReads,
    query: ListeningQuery,
    selection: SessionSelection,
    options: RecordOptions,
) -> ListeningSessionDetail:
    """Open only the source rows belonging to one exact inferred group.

    Args:
        index: Pinned immutable history generation.
        query: The same selection used to group the records.
        selection: Group's first recorded timestamp and the gap in minutes.
        options: Bounded chronological source-record page.

    Returns:
        The exact group definition and original selected source records.

    Raises:
        ListeningEntityError: The identifier does not start a group in this context.
    """
    groups = _groups(index, query, selection.gap_minutes)
    group = _find_group(groups, selection.first_ms)
    records = index.session_records(query, group.window, options)
    return ListeningSessionDetail(group, selection.gap_minutes, records)
