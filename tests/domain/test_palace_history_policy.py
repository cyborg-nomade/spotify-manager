"""Protect Palace calendar bounds and seconds-only ranks independently of adapters."""

from datetime import UTC
from datetime import date
from datetime import datetime

import pytest

from spotify_manager.domain.history import HistoricalAlbum
from spotify_manager.domain.history import Scrobble
from spotify_manager.domain.palace_history import cutoff
from spotify_manager.domain.palace_history import dated_rankings
from spotify_manager.domain.palace_history import selected_albums


def test_palace_history_uses_inclusive_dates_and_ignores_blank_albums() -> None:
    """Keep original first-seen display names and sorted historical date indexing."""
    first = date(2007, 11, 27)
    last = date(2025, 12, 31)
    album = Scrobble("Track", "Artist", "Album", 100)
    history = {
        last: [album],
        date(2026, 1, 1): [album],
        first: [album],
        date(2007, 11, 26): [album],
        date(2020, 1, 1): [Scrobble("Track", "Artist", "", 100)],
    }
    assert dated_rankings(history, first, last) == {
        last: (HistoricalAlbum("Artist", "Album", 1),),
        first: (HistoricalAlbum("Artist", "Album", 1),),
    }
    assert cutoff(date(2026, 1, 1)) == last
    assert cutoff(date(2026, 12, 31)) == last


@pytest.mark.parametrize("second,position", [(0, 1), (1, 2), (2, 1), (59, 2)])
def test_palace_historical_rank_uses_only_seconds_and_retains_index_order(
    second: int,
    position: int,
) -> None:
    """Keep original wrapped rank and custom-reader duplicate date positions.

    Args:
        second: Original Random.org timestamp second.
        position: Original selected one-based rank.
    """
    first = date(2020, 1, 1)
    last = date(2021, 1, 1)
    albums = (
        HistoricalAlbum("Artist", "Alpha", 3),
        HistoricalAlbum("Artist", "Zulu", 2),
    )
    selected = selected_albums(
        {last: albums, first: albums},
        (1, 1, 0),
        datetime(2026, 8, 8, 12, 47, second, tzinfo=UTC),
    )
    assert tuple(item.selected_date for item in selected) == (last, last, first)
    assert tuple(item.position for item in selected) == (position,) * 3
    assert selected_albums({}, (), datetime(2026, 8, 8, tzinfo=UTC)) == ()


def test_palace_historical_reader_retains_out_of_range_error() -> None:
    """Retain the original custom-reader indexing error without extra validation."""
    with pytest.raises(IndexError):
        selected_albums({}, (0,), datetime(2026, 8, 8, tzinfo=UTC))
