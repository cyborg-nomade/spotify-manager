"""Verify exact local-hour counts and bounded, contiguous calendar columns."""

from datetime import date
from datetime import timedelta

import pytest

from spotify_manager.domain.listening_scrobble_map import MAX_PERIODS
from spotify_manager.domain.listening_scrobble_map import HourPlayCount
from spotify_manager.domain.listening_scrobble_map import MapGrain
from spotify_manager.domain.listening_scrobble_map import ScrobbleMapCell
from spotify_manager.domain.listening_scrobble_map import build_scrobble_map
from spotify_manager.domain.listening_values import ListeningQuery


@pytest.mark.parametrize(
    ("start", "end", "grain"),
    [
        ("2024-01-03", "2024-02-02", "day"),
        ("2024-01-03", "2024-12-29", "week"),
        ("2024-01-03", "2030-10-25", "month"),
        ("2000-01-03", "2024-02-03", "quarter"),
        ("1900-07-12", "2000-07-12", "year"),
    ],
)
def test_calendar_adapts_and_keeps_exact_partial_period_bounds(
    start: str, end: str, grain: MapGrain
) -> None:
    """Use the finest scale within the rendering bound and include empty dates."""
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    query = ListeningQuery(first, last, "UTC")
    counts = (HourPlayCount(first, 7, 2), HourPlayCount(last, 7, 3))
    result = build_scrobble_map(counts, query, (first, last))
    assert result.grain == grain and result.plays == 5
    assert len(result.periods) <= MAX_PERIODS
    assert result.periods[0].start == first and result.periods[-1].end == last
    for left, right in zip(result.periods[:-1], result.periods[1:], strict=True):
        assert left.end + timedelta(days=1) == right.start
    assert result.cells == (
        ScrobbleMapCell(0, 7, 2),
        ScrobbleMapCell(len(result.periods) - 1, 7, 3),
    )


def test_weekly_cells_sum_multiple_days_at_the_same_hour() -> None:
    """Sum only the same selected hour and keep the week clipped at the start."""
    start = date(2024, 1, 3)
    query = ListeningQuery(start, date(2024, 12, 31), "UTC")
    counts = (
        HourPlayCount(start, 11, 3),
        HourPlayCount(start + timedelta(days=1), 11, 5),
        HourPlayCount(start + timedelta(days=1), 12, 2),
    )
    result = build_scrobble_map(counts, query, (start, query.end))
    assert result.grain == "week"
    assert result.periods[0].end == date(2024, 1, 7)
    assert result.cells == (ScrobbleMapCell(0, 11, 8), ScrobbleMapCell(0, 12, 2))
    assert result.plays == 10
