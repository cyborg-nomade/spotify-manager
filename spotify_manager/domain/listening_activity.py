"""Recorded listening counts, daily coverage, and weekly rhythm."""

from collections import Counter
from datetime import timedelta

from spotify_manager.domain.listening_time import hour_occurrences
from spotify_manager.domain.listening_time import local_instant
from spotify_manager.domain.listening_values import ListeningActivity
from spotify_manager.domain.listening_values import ListeningCounts
from spotify_manager.domain.listening_values import ListeningDay
from spotify_manager.domain.listening_values import ListeningHour
from spotify_manager.domain.listening_values import ListeningOverview
from spotify_manager.domain.listening_values import ListeningQuery


def summarize_listening(
    counts: ListeningCounts, query: ListeningQuery
) -> ListeningOverview:
    """Label calendar-day and active-day averages with separate denominators.

    Args:
        counts: Exact filtered counts.
        query: Requested calendar interval.

    Returns:
        Counts and averages, including zero-result selections.
    """
    days = (query.end - query.start).days + 1
    return ListeningOverview(
        counts,
        days,
        counts.scrobbles / days,
        counts.scrobbles / counts.active_days if counts.active_days else 0,
    )


def listening_activity(
    timestamps: tuple[int, ...],
    query: ListeningQuery,
    coverage: tuple[int | None, int | None],
) -> ListeningActivity:
    """Aggregate UTC observations into complete local date/hour buckets.

    Args:
        timestamps: Filtered recorded instants, retaining duplicates.
        query: Selected local dates and rhythm.
        coverage: Full source observation bounds.

    Returns:
        Daily coverage markers and 168 hour cells.
    """
    days: Counter[str] = Counter()
    hours: Counter[tuple[int, int]] = Counter()
    for timestamp in timestamps:
        instant = local_instant(timestamp, query.timezone)
        days[instant.date().isoformat()] += 1
        hours[(instant.weekday(), instant.hour)] += 1
    return ListeningActivity(
        _days(days, query, coverage), _hours(hours, query, coverage)
    )


def _days(
    counts: Counter[str],
    query: ListeningQuery,
    coverage: tuple[int | None, int | None],
) -> tuple[ListeningDay, ...]:
    first, last = coverage
    first_day = (
        local_instant(first, query.timezone).date() if first is not None else None
    )
    last_day = local_instant(last, query.timezone).date() if last is not None else None
    result = []
    day = query.start
    while day <= query.end:
        covered = False
        if first_day is not None and last_day is not None:
            covered = first_day <= day <= last_day
        partial = day in (first_day, last_day)
        result.append(ListeningDay(day, counts[day.isoformat()], covered, partial))
        day += timedelta(days=1)
    return tuple(result)


def _hours(
    counts: Counter[tuple[int, int]],
    query: ListeningQuery,
    coverage: tuple[int | None, int | None],
) -> tuple[ListeningHour, ...]:
    occurrences = hour_occurrences(query, coverage)
    result = []
    for cell in range(168):
        weekday, hour = divmod(cell, 24)
        plays = counts[(weekday, hour)]
        denominator = occurrences.get((weekday, hour), 0)
        average = plays / denominator if denominator else 0
        result.append(ListeningHour(weekday, hour, plays, denominator, average))
    return tuple(result)
