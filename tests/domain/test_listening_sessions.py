"""Hand-check selected-record grouping independently of storage and HTTP."""

from datetime import date

import pytest

from spotify_manager.domain.listening_session_values import SessionOptions
from spotify_manager.domain.listening_sessions import group_listening_sessions
from spotify_manager.domain.listening_sessions import listening_sessions
from spotify_manager.domain.listening_values import ArtistPlay
from spotify_manager.domain.listening_values import ListeningQuery
from tests.support.listening import timestamp


QUERY = ListeningQuery(date(2024, 1, 1), date(2024, 1, 31), "UTC")


def play(when: str, artist: str = "Alpha", track: str = "Same") -> ArtistPlay:
    """Build a compact independent observation.

    Args:
        when: Explicit UTC fixture timestamp.
        artist: Case-sensitive test identity and display name.
        track: Artist-qualified test track identity.

    Returns:
        One chronological-rule input, without network or source parsing.
    """
    return ArtistPlay(timestamp(when), artist, artist, artist + "/" + track)


def test_exact_threshold_duplicates_and_zero_span_are_preserved() -> None:
    """Equal gaps stay together; one extra millisecond starts a distinct group."""
    first = play("2024-01-01T12:00:00")
    same = play("2024-01-01T12:30:00", "Other")
    later = play("2024-01-01T13:00:00.001")
    groups = group_listening_sessions((first, first, same, later), 30)
    assert [group.plays for group in groups] == [3, 1]
    assert groups[0].artists == groups[0].tracks == 2
    assert groups[0].leading_artist.name == "Alpha"
    assert groups[0].leading_artist.plays == 2
    assert groups[0].leading_artist.share == 2 / 3
    assert groups[0].selection_first and not groups[0].selection_last
    assert groups[1].selection_last and not groups[1].selection_first
    assert groups[1].window.first_ms == groups[1].window.last_ms


def test_leading_artist_ties_use_record_order_and_qualified_tracks() -> None:
    """Names retain accents and equal-count leaders follow the first record."""
    plays = (play("2024-01-01T12:00:00", "Béta"), play("2024-01-01T12:01:00", "Beta"))
    group = group_listening_sessions(plays, 30)[0]
    assert group.artists == group.tracks == 2
    assert group.leading_artist.name == "Béta"
    assert group.selection_first and group.selection_last


@pytest.mark.parametrize("zone", ["UTC", "Europe/Berlin", "America/New_York"])
def test_midnight_and_dst_never_change_utc_gap_groups(zone: str) -> None:
    """Local midnight and repeated or skipped hours only affect display buckets.

    Args:
        zone: Independently chosen display timezone.
    """
    plays = (
        play("2024-03-31T00:50:00"),
        play("2024-03-31T01:10:00"),
        play("2024-10-27T00:50:00"),
        play("2024-10-27T01:10:00"),
    )
    groups = group_listening_sessions(plays, 30)
    query = ListeningQuery(date(2024, 3, 30), date(2024, 10, 28), zone)
    data = listening_sessions(groups, query, SessionOptions())
    assert [group.plays for group in groups] == [2, 2]
    for group in groups:
        assert group.window.last_ms - group.window.first_ms == 1200000
    assert sum(bucket.sessions for bucket in data.buckets) == 2
    assert sum(bucket.plays for bucket in data.buckets) == 4
    assert data.grain == "month"


def test_cross_midnight_group_is_attributed_to_its_first_local_record() -> None:
    """A single group contributes its rows once, even across a calendar boundary."""
    groups = group_listening_sessions(
        (play("2024-01-07T23:50:00"), play("2024-01-08T00:10:00")), 30
    )
    data = listening_sessions(groups, QUERY, SessionOptions())
    assert data.grain == "week"
    assert data.buckets[0].label == "2024-01-01"
    assert data.buckets[0].sessions == 1 and data.buckets[0].plays == 2
    assert data.buckets[1].sessions == data.buckets[1].plays == 0


def test_minimum_size_pagination_and_order_never_change_full_coverage() -> None:
    """Display options apply after complete grouping; equal sizes sort by recency."""
    plays = (
        play("2024-01-01T12:00:00"),
        play("2024-01-01T12:01:00"),
        play("2024-01-02T12:00:00"),
        play("2024-01-03T12:00:00"),
        play("2024-01-03T12:01:00"),
    )
    groups = group_listening_sessions(plays, 30)
    first = listening_sessions(
        groups, QUERY, SessionOptions(minimum_plays=2, order="plays", limit=1)
    )
    second = listening_sessions(
        groups, QUERY, SessionOptions(minimum_plays=2, order="plays", page=2, limit=1)
    )
    assert first.items[0].window.first_ms == timestamp("2024-01-03T12:00:00")
    assert second.items[0].window.first_ms == timestamp("2024-01-01T12:00:00")
    assert first.summary == second.summary
    assert first.summary.selected_plays == 5 and first.summary.selected_sessions == 3
    assert first.summary.matching_plays == 4 and first.summary.matching_sessions == 2
    assert first.summary.median_plays == 2 and first.summary.median_span_ms == 60000
    assert first.buckets == second.buckets and first.sizes == second.sizes
    empty_page = listening_sessions(groups, QUERY, SessionOptions(page=100))
    assert empty_page.items == () and empty_page.summary.selected_plays == 5


@pytest.mark.parametrize(
    "size,band",
    [
        (1, 0),
        (2, 1),
        (5, 1),
        (6, 2),
        (10, 2),
        (11, 3),
        (25, 3),
        (26, 4),
        (50, 4),
        (51, 5),
    ],
)
def test_size_bands_conserve_groups_and_duplicate_rows(size: int, band: int) -> None:
    """Every inclusive size boundary belongs to exactly one chart band.

    Args:
        size: Hand-counted duplicate source rows.
        band: Independent expected size-band position.
    """
    groups = group_listening_sessions((play("2024-01-01T12:00:00"),) * size, 30)
    data = listening_sessions(groups, QUERY, SessionOptions())
    assert data.sizes[band].sessions == 1 and data.sizes[band].plays == size
    assert sum(item.sessions for item in data.sizes) == 1
    assert sum(item.plays for item in data.sizes) == size


@pytest.mark.parametrize("filtered", [False, True])
def test_empty_and_all_excluded_selections_keep_complete_empty_buckets(
    filtered: bool,
) -> None:
    """No results retain selected totals and avoid undefined medians.

    Args:
        filtered: Whether a real singleton is excluded by the minimum size.
    """
    plays = (play("2024-01-01T12:00:00"),) if filtered else ()
    groups = group_listening_sessions(plays, 30)
    data = listening_sessions(groups, QUERY, SessionOptions(minimum_plays=2))
    assert data.items == () and data.summary.matching_sessions == 0
    assert data.summary.selected_plays == int(filtered)
    assert data.summary.median_plays == data.summary.median_span_ms == 0
    assert len(data.buckets) == 5 and all(item.plays == 0 for item in data.buckets)
    assert len(data.sizes) == 6 and all(item.sessions == 0 for item in data.sizes)
