"""Verify named session use cases against independently published source rows."""

from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from spotify_manager.application.listening_ports import ListeningEntityError
from spotify_manager.application.listening_sessions import get_listening_session_records
from spotify_manager.application.listening_sessions import get_listening_sessions
from spotify_manager.core.library_data.models import artifact_metadata
from spotify_manager.domain.listening_session_values import SessionOptions
from spotify_manager.domain.listening_session_values import SessionSelection
from spotify_manager.domain.listening_time import listening_identity
from spotify_manager.domain.listening_values import ListeningQuery
from spotify_manager.domain.listening_values import RecordOptions
from spotify_manager.infrastructure.listening.build import build_listening_index
from spotify_manager.infrastructure.listening.reader import ListeningIndex
from tests.support.listening import listening_fixture
from tests.support.listening import scrobble
from tests.support.listening import timestamp
from tests.support.listening_sessions import session_history


QUERY = ListeningQuery(date(2024, 1, 1), date(2024, 1, 3), "UTC")


def session_index(root: Path) -> ListeningIndex:
    """Build a concrete immutable reader from a deliberate unsorted publication.

    Args:
        root: Isolated test-owned source and cache directory.

    Returns:
        Complete verified generation with known gap groups.
    """
    fixture = listening_fixture(root)
    fixture.publish(session_history())
    return fixture.index()


def test_grouping_and_original_records_reconcile_without_changing_authorities(
    tmp_path: Path,
) -> None:
    """Actual SQL sorts source disorder and retains duplicate source ordinals.

    Args:
        tmp_path: Isolated test-owned storage.
    """
    fixture = listening_fixture(tmp_path)
    fixture.publish(session_history())
    before = fixture.service.snapshot()
    original = fixture.source.read_bytes()
    index = fixture.index()
    data = get_listening_sessions(index, QUERY, SessionOptions(order="plays"))
    assert [group.plays for group in data.items] == [4, 3, 1]
    assert data.summary.selected_plays == index.counts(QUERY).scrobbles == 8
    selection = SessionSelection(timestamp("2024-01-01T12:00:00"))
    page = get_listening_session_records(
        index, QUERY, selection, RecordOptions(limit=2)
    )
    assert [row.ordinal for row in page.records.items] == [1, 2]
    next_page = get_listening_session_records(
        index, QUERY, selection, RecordOptions(page=2, limit=2)
    )
    assert [row.ordinal for row in next_page.records.items] == [4, 3]
    assert page.records.total == page.session.plays == 4
    assert (
        fixture.source.read_bytes() == original and fixture.service.snapshot() == before
    )


def test_gap_and_filters_are_applied_before_groups_and_size_afterwards(
    tmp_path: Path,
) -> None:
    """Date/artist/rhythm selection never leaks excluded rows into a detail page.

    Args:
        tmp_path: Isolated concrete reader storage.
    """
    index = session_index(tmp_path)
    alpha = replace(QUERY, artist=listening_identity(("Alpha",)))
    data = get_listening_sessions(index, alpha, SessionOptions())
    assert data.summary.selected_plays == 3 and data.summary.selected_sessions == 2
    detail = get_listening_session_records(
        index,
        alpha,
        SessionSelection(timestamp("2024-01-01T12:00:00")),
        RecordOptions(),
    )
    assert [item.artist for item in detail.records.items] == ["Alpha", "Alpha"]
    narrow = replace(QUERY, start=date(2024, 1, 2), end=date(2024, 1, 2))
    selected = get_listening_sessions(index, narrow, SessionOptions())
    assert selected.summary.selected_plays == 2 and selected.items[
        0
    ].window.first_ms == timestamp("2024-01-02T00:00:00")
    rhythm = replace(QUERY, weekday=1, hour=0)
    assert (
        get_listening_sessions(index, rhythm, SessionOptions()).summary.selected_plays
        == 2
    )
    smaller_gap = get_listening_sessions(index, QUERY, SessionOptions(gap_minutes=15))
    assert smaller_gap.summary.selected_sessions == 5
    assert (
        get_listening_sessions(
            index, QUERY, SessionOptions(minimum_plays=4)
        ).summary.matching_plays
        == 4
    )


def test_group_identifiers_are_valid_only_for_the_exact_context(tmp_path: Path) -> None:
    """An interior timestamp cannot silently select part of a different group.

    Args:
        tmp_path: Isolated concrete reader storage.
    """
    index = session_index(tmp_path)
    with pytest.raises(ListeningEntityError):
        get_listening_session_records(
            index,
            QUERY,
            SessionSelection(timestamp("2024-01-01T12:01:00")),
            RecordOptions(),
        )
    with pytest.raises(ListeningEntityError):
        get_listening_session_records(
            index,
            replace(QUERY, hour=23),
            SessionSelection(timestamp("2024-01-01T12:00:00")),
            RecordOptions(),
        )
    detail = get_listening_session_records(
        index,
        QUERY,
        SessionSelection(timestamp("2024-01-01T23:40:00")),
        RecordOptions(page=50),
    )
    assert (
        detail.records.items == () and detail.records.total == detail.session.plays == 3
    )


def test_correction_with_same_size_gets_new_groups_and_caches(tmp_path: Path) -> None:
    """A complete corrected generation cannot reuse an earlier session result.

    Args:
        tmp_path: Isolated canonical publication and derived generations.
    """
    fixture = listening_fixture(tmp_path)
    fixture.publish([scrobble("2024-01-01T12:00:00"), scrobble("2024-01-01T12:01:00")])
    first = fixture.index()
    data = get_listening_sessions(first, QUERY, SessionOptions())
    fixture.publish([scrobble("2024-01-01T12:00:00"), scrobble("2024-01-01T13:00:00")])
    metadata = artifact_metadata(fixture.service.snapshot().document, "scrobbles")
    assert metadata is not None
    path = tmp_path / "second.sqlite"
    second = ListeningIndex(path, build_listening_index(fixture.source, path, metadata))
    corrected = get_listening_sessions(second, QUERY, SessionOptions())
    assert first.metadata.snapshot != second.metadata.snapshot
    assert data.summary.selected_plays == corrected.summary.selected_plays == 2
    assert (
        data.summary.selected_sessions == 1 and corrected.summary.selected_sessions == 2
    )
