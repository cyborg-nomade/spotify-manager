"""Recorded listening anniversaries and transparent artist-share similarity."""

from calendar import isleap
from calendar import monthrange
from collections import Counter
from datetime import date
from typing import Literal

from spotify_manager.domain.listening_capsule_values import AnniversaryDay
from spotify_manager.domain.listening_capsule_values import EraPeriod
from spotify_manager.domain.listening_capsule_values import ListeningAnniversaries
from spotify_manager.domain.listening_capsule_values import ListeningEras
from spotify_manager.domain.listening_time import local_instant
from spotify_manager.domain.listening_values import ArtistPlay
from spotify_manager.domain.listening_values import ListeningQuery
from spotify_manager.domain.listening_values import RankedEntity


type Coverage = tuple[date, date] | None


def listening_eras(
    plays: tuple[ArtistPlay, ...],
    query: ListeningQuery,
    coverage: tuple[int | None, int | None],
) -> ListeningEras:
    """Compare all recorded artists, normalizing away period listening volume.

    Args:
        plays: Observations already restricted to the shared selection.
        query: Selected local dates, artist and rhythm.
        coverage: Global source bounds in UTC milliseconds.

    Returns:
        Monthly similarity, using years beyond 240 months to bound the matrix.
        A comparison involving an empty period is undefined, including itself.
    """
    months = (query.end.year - query.start.year) * 12
    months += query.end.month - query.start.month + 1
    grain: Literal["month", "year"] = "month" if months <= 240 else "year"
    counters = _era_counts(plays, query, grain)
    observed = _coverage(coverage, query.timezone)
    periods = []
    shares = []
    for name in _period_names(query, grain):
        counts = counters.get(name, Counter())
        periods.append(_era_period(name, counts, query, observed))
        shares.append(_artist_shares(counts))
    return ListeningEras(grain, tuple(periods), _similarity_matrix(shares))


def _period_names(query: ListeningQuery, grain: str) -> tuple[str, ...]:
    if grain == "year":
        return tuple(str(year) for year in range(query.start.year, query.end.year + 1))
    result = []
    first = query.start.year * 12 + query.start.month - 1
    last = query.end.year * 12 + query.end.month - 1
    for value in range(first, last + 1):
        year, month = divmod(value, 12)
        result.append(f"{year:04d}-{month + 1:02d}")
    return tuple(result)


def _era_counts(
    plays: tuple[ArtistPlay, ...], query: ListeningQuery, grain: str
) -> dict[str, Counter[str]]:
    counters: dict[str, Counter[str]] = {}
    for play in plays:
        day = local_instant(play.timestamp_ms, query.timezone).date()
        name = day.isoformat()[:7] if grain == "month" else str(day.year)
        counters.setdefault(name, Counter())[play.artist_key] += 1
    return counters


def _coverage(bounds: tuple[int | None, int | None], timezone: str) -> Coverage:
    first, last = bounds
    if first is None or last is None:
        return None
    return local_instant(first, timezone).date(), local_instant(last, timezone).date()


def _covered(start: date, end: date, observed: Coverage) -> tuple[bool, bool]:
    if observed is None or end < observed[0] or start > observed[1]:
        return False, False
    partial = start <= observed[0] <= end or start <= observed[1] <= end
    return True, partial


def _period_bounds(name: str) -> tuple[date, date]:
    year = int(name[:4])
    if len(name) == 4:
        return date(year, 1, 1), date(year, 12, 31)
    month = int(name[5:])
    return date(year, month, 1), date(year, month, monthrange(year, month)[1])


def _era_period(
    name: str, counts: Counter[str], query: ListeningQuery, observed: Coverage
) -> EraPeriod:
    first, last = _period_bounds(name)
    start, end = max(first, query.start), min(last, query.end)
    covered, partial = _covered(start, end, observed)
    partial = covered and (partial or start != first or end != last)
    return EraPeriod(name, start, end, counts.total(), len(counts), covered, partial)


def _artist_shares(counts: Counter[str]) -> dict[str, float]:
    total = counts.total()
    shares = {}
    for key, count in counts.items():
        shares[key] = count / total
    return shares


def _weighted_jaccard(left: dict[str, float], right: dict[str, float]) -> float | None:
    if not left or not right:
        return None
    intersection = 0.0
    for key in left.keys() & right.keys():
        intersection += min(left[key], right[key])
    intersection = min(1.0, intersection)
    return round(intersection / (2.0 - intersection), 6)


def _similarity_matrix(
    shares: list[dict[str, float]],
) -> tuple[tuple[float | None, ...], ...]:
    matrix: list[list[float | None]] = []
    for _item in shares:
        matrix.append([None] * len(shares))
    for left in range(len(shares)):
        for right in range(left, len(shares)):
            similarity = _weighted_jaccard(shares[left], shares[right])
            matrix[left][right] = similarity
            matrix[right][left] = similarity
    return tuple(tuple(row) for row in matrix)


def listening_anniversaries(
    plays: tuple[ArtistPlay, ...],
    query: ListeningQuery,
    coverage: tuple[int | None, int | None],
) -> ListeningAnniversaries:
    """Find the same local month/day in every earlier source year.

    Args:
        plays: Artist-filtered full history through the analysis end date.
        query: Analysis end defining the anniversary; visible start is ignored.
        coverage: Global source bounds, independent of artist filtering.

    Returns:
        Earlier anniversaries with source coverage and five leading artists.
        February 29 appears only in leap years; no current or future year leaks in.
    """
    observed = _coverage(coverage, query.timezone)
    if observed is None:
        return ListeningAnniversaries(query.end, (), None, None)
    counts, names = _anniversary_counts(plays, query)
    days = []
    for year in range(observed[0].year, query.end.year):
        day = _anniversary_date(query.end, year)
        if day is not None:
            days.append(
                _anniversary_day(day, counts.get(day, Counter()), names, observed)
            )
    return ListeningAnniversaries(query.end, tuple(days), observed[0], observed[1])


def _anniversary_date(anchor: date, year: int) -> date | None:
    if anchor.month == 2 and anchor.day == 29 and not isleap(year):
        return None
    return date(year, anchor.month, anchor.day)


def _anniversary_counts(
    plays: tuple[ArtistPlay, ...], query: ListeningQuery
) -> tuple[dict[date, Counter[str]], dict[str, str]]:
    counters: dict[date, Counter[str]] = {}
    names: dict[str, str] = {}
    for play in plays:
        day = local_instant(play.timestamp_ms, query.timezone).date()
        if day.year >= query.end.year or (day.month, day.day) != (
            query.end.month,
            query.end.day,
        ):
            continue
        counters.setdefault(day, Counter())[play.artist_key] += 1
        names.setdefault(play.artist_key, play.artist_name)
    return counters, names


def _anniversary_day(
    day: date, counts: Counter[str], names: dict[str, str], observed: Coverage
) -> AnniversaryDay:
    top = []
    for key, count in counts.most_common(5):
        top.append(
            RankedEntity(key, names[key], names[key], count, count / counts.total())
        )
    covered, partial = _covered(day, day, observed)
    return AnniversaryDay(
        day, counts.total(), len(counts), tuple(top), covered, partial
    )
