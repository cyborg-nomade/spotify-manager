"""Historical date, timestamp, and album-ranking contracts."""

from datetime import UTC
from datetime import date
from datetime import datetime

import pytest

from spotify_manager.domain.history import HistoricalAlbum
from spotify_manager.domain.history import Scrobble
from spotify_manager.domain.history import eligible_dates
from spotify_manager.domain.history import historical_album_offset
from spotify_manager.domain.history import normalize_name
from spotify_manager.domain.history import page_for_timestamp
from spotify_manager.domain.history import rank_albums
from spotify_manager.domain.history import select_scrobble


def _timestamp(hour: int = 13, minute: int = 0, second: int = 0) -> datetime:
    return datetime(2026, 9, 25, hour, minute, second, tzinfo=UTC)


def _scrobbles(count: int) -> list[Scrobble]:
    return [Scrobble(str(index), "Artist", "Album", index) for index in range(count)]


@pytest.mark.parametrize(
    "hour,minute,pages,expected",
    [
        (13, 0, 7, 7),
        (12, 0, 7, 6),
        (13, 0, 6, 6),
        (23, 1, 7, 6),
        (13, 10, 7, 1),
        (13, 20, 7, 2),
        (13, 59, 7, 5),
        (13, 0, 2, 2),
    ],
)
def test_track_page_selection(
    hour: int, minute: int, pages: int, expected: int
) -> None:
    """Retain minute-digit selection, wrapping, and the seventh-page exception.

    Args:
        hour: Random timestamp hour.
        minute: Random timestamp minute.
        pages: Number of populated pages.
        expected: One-based selected page.
    """
    assert page_for_timestamp(_timestamp(hour, minute), pages) == expected


@pytest.mark.parametrize("pages", [0, -1])
def test_empty_page_population_is_rejected(pages: int) -> None:
    """Preserve the exact error for an empty historical page population.

    Args:
        pages: Invalid page count.
    """
    with pytest.raises(ValueError, match="total_pages must be at least 1"):
        page_for_timestamp(_timestamp(), pages)


@pytest.mark.parametrize(
    "minute,second,expected_page,position,track",
    [
        (0, 58, 2, 3, "52"),
        (5, 58, 2, 3, "54"),
        (10, 2, 1, 3, "2"),
        (15, 2, 1, 3, "47"),
        (14, 2, 1, 3, "2"),
        (19, 2, 1, 3, "47"),
    ],
)
def test_historical_track_selection(
    minute: int,
    second: int,
    expected_page: int,
    position: int,
    track: str,
) -> None:
    """Wrap seconds within the selected page, respecting its direction and short tail.

    Args:
        minute: Random timestamp minute.
        second: Random timestamp second.
        expected_page: Selected one-based page.
        position: Selected one-based position in directional order.
        track: Expected track identity.
    """
    scrobbles = _scrobbles(57)
    result = select_scrobble(
        date(2020, 1, 1), 4, scrobbles, _timestamp(13, minute, second)
    )
    assert (result.page, result.position, result.scrobble.track) == (
        expected_page,
        position,
        track,
    )
    assert result.selected_date == date(2020, 1, 1)
    assert result.date_index == 4
    assert result.scrobbles_on_date == 57 and result.total_pages == 2
    assert result.scrobble is scrobbles[int(track)]
    assert result.direction == ("top down" if minute % 10 <= 4 else "bottom up")


def test_empty_scrobble_date_preserves_error() -> None:
    """Reject an empty selected date before attempting page arithmetic."""
    with pytest.raises(ValueError, match="cannot select from a date without scrobbles"):
        select_scrobble(date(2020, 1, 1), 0, [], _timestamp())


def test_explicit_page_size_preserves_boundary_configuration() -> None:
    """Let the compatibility boundary supply its existing page-size constant."""
    result = select_scrobble(
        date(2020, 1, 1), 0, _scrobbles(4), _timestamp(13, 10, 2), 3
    )
    assert result.total_pages == 2
    assert result.scrobble.track == "2"
    with pytest.raises(ZeroDivisionError):
        select_scrobble(date(2020, 1, 1), 0, _scrobbles(4), _timestamp(), 0)


def test_eligible_dates_include_bounds_and_exclude_empty_days() -> None:
    """Sort only populated dates within both inclusive date boundaries."""
    plays = _scrobbles(1)
    history = {
        date(2020, 1, 4): plays,
        date(2020, 1, 3): plays,
        date(2020, 1, 2): [],
        date(2020, 1, 1): plays,
        date(2019, 12, 31): plays,
    }
    assert eligible_dates(history, date(2020, 1, 1), date(2020, 1, 3)) == [
        date(2020, 1, 1),
        date(2020, 1, 3),
    ]


def test_album_ranking_preserves_first_names_and_tie_order() -> None:
    """Merge normalized identities while retaining names and album/artist tie order."""
    plays = [
        Scrobble("one", "Björk", "Álbum", 1),
        Scrobble("two", "bjork", "album", 2),
        Scrobble("one", "Zed", "Beta", 3),
        Scrobble("one", "Able", "Beta", 4),
        Scrobble("one", "Artist", "  ", 5),
        Scrobble("one", "!!!", "Album", 6),
        Scrobble("one", "Artist", "!!!", 7),
    ]
    assert rank_albums(plays) == (
        HistoricalAlbum("Björk", "Álbum", 2),
        HistoricalAlbum("Able", "Beta", 1),
        HistoricalAlbum("Zed", "Beta", 1),
    )
    assert rank_albums([]) == ()
    assert normalize_name(" AC / DC ") == "acdc"


def test_palace_rank_uses_seconds_only() -> None:
    """Keep Palace album ranks independent of the track-page timestamp policy."""
    assert historical_album_offset(_timestamp(13, 0, 59), 7) == 3
    assert historical_album_offset(_timestamp(1, 59, 59), 7) == 3
    with pytest.raises(ZeroDivisionError):
        historical_album_offset(_timestamp(), 0)
