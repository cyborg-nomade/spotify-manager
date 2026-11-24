"""Bucket recorded plays by calendar period and local wall-clock hour."""

from collections import Counter
from dataclasses import dataclass
from datetime import date
from datetime import timedelta
from typing import Literal

from spotify_manager.domain.listening_time import local_instant
from spotify_manager.domain.listening_values import ListeningQuery


type MapGrain = Literal["day", "week", "month", "quarter", "year"]
MAX_PERIODS = 240
MAX_POINT_DAYS = 31
MAX_POINTS = 5000
GRAINS: tuple[MapGrain, ...] = ("day", "week", "month", "quarter", "year")


@dataclass(frozen=True)
class HourPlayCount:
    """Count recorded rows for one local day and hour, including duplicates."""

    day: date
    hour: int
    plays: int


@dataclass(frozen=True)
class ScrobbleMapPeriod:
    """Keep the inclusive, selection-clipped bounds for one column."""

    start: date
    end: date


@dataclass(frozen=True)
class ScrobbleMapCell:
    """Identify a populated date-column and local hour with its exact play count."""

    period: int
    hour: int
    plays: int


@dataclass(frozen=True)
class ScrobbleMapPoint:
    """Keep the original timestamp and its position on the local calendar."""

    period: int
    local_ms: int
    timestamp_ms: int


@dataclass(frozen=True)
class ListeningScrobbleMap:
    """Describe sparse scrobble density and the complete selected calendar axis."""

    grain: MapGrain
    periods: tuple[ScrobbleMapPeriod, ...]
    cells: tuple[ScrobbleMapCell, ...]
    plays: int
    observed_from: date | None
    observed_through: date | None
    points: tuple[ScrobbleMapPoint, ...] | None = None


def _anchor(day: date, grain: MapGrain) -> date:
    if grain == "day":
        return day
    if grain == "week":
        return day - timedelta(days=day.weekday())
    months = {"month": 1, "quarter": 3, "year": 12}[grain]
    return date(day.year, 1 + (day.month - 1) // months * months, 1)


def _following(start: date, grain: MapGrain) -> date:
    if grain == "day" or grain == "week":
        return start + timedelta(days=1 if grain == "day" else 7)
    months = {"month": 1, "quarter": 3, "year": 12}[grain]
    year, month = divmod(start.year * 12 + start.month - 1 + months, 12)
    return date(year, month + 1, 1)


def _periods(query: ListeningQuery, grain: MapGrain) -> tuple[ScrobbleMapPeriod, ...]:
    result: list[ScrobbleMapPeriod] = []
    start = _anchor(query.start, grain)
    while start <= query.end and len(result) <= MAX_PERIODS:
        following = _following(start, grain)
        end = min(query.end, following - timedelta(days=1))
        result.append(ScrobbleMapPeriod(max(start, query.start), end))
        start = following
    return tuple(result)


def _calendar(query: ListeningQuery) -> tuple[MapGrain, tuple[ScrobbleMapPeriod, ...]]:
    for grain in GRAINS:
        periods = _periods(query, grain)
        if len(periods) <= MAX_PERIODS:
            return grain, periods
    raise ValueError("The selection exceeds the supported scrobble-map date range.")


def build_scrobble_map(
    counts: tuple[HourPlayCount, ...],
    query: ListeningQuery,
    observed: tuple[date | None, date | None],
) -> ListeningScrobbleMap:
    """Group all selected scrobbles into the finest bounded calendar scale.

    Args:
        counts: Exact selected local day/hour counts from the history index.
        query: Inclusive dates used by the index and the column axis.
        observed: First and last local dates in the published history.

    Returns:
        At most 240 chronological columns, their populated hours and exact totals.
    """
    grain, periods = _calendar(query)
    indices = {}
    for index, period in enumerate(periods):
        indices[_anchor(period.start, grain)] = index
    grouped: Counter[tuple[int, int]] = Counter()
    for row in counts:
        index = indices[_anchor(row.day, grain)]
        grouped[index, row.hour] += row.plays
    cells = tuple(ScrobbleMapCell(*key, grouped[key]) for key in sorted(grouped))
    return ListeningScrobbleMap(grain, periods, cells, grouped.total(), *observed)


def build_scrobble_points(
    timestamps: tuple[int, ...], query: ListeningQuery
) -> tuple[ScrobbleMapPoint, ...]:
    """Position each original recorded play within its day and local clock.

    Args:
        timestamps: Bounded UTC observations in milliseconds, including duplicates.
        query: Inclusive selected days and local display timezone.

    Returns:
        One point per played row, ordered by recorded UTC time.
    """
    result = []
    for timestamp in sorted(timestamps):
        instant = local_instant(timestamp, query.timezone)
        period = (instant.date() - query.start).days
        seconds = instant.hour * 3600 + instant.minute * 60 + instant.second
        local_ms = seconds * 1000 + instant.microsecond // 1000
        result.append(ScrobbleMapPoint(period, local_ms, timestamp))
    return tuple(result)
