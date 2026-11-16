"""Transparent discovery, inactivity, and period-comparison rules."""

from collections import Counter
from dataclasses import dataclass
from dataclasses import field
from datetime import date
from datetime import timedelta

from spotify_manager.domain.listening_time import local_instant
from spotify_manager.domain.listening_values import ArtistPlay
from spotify_manager.domain.listening_values import DiscoveryCohort
from spotify_manager.domain.listening_values import EntityLifetime
from spotify_manager.domain.listening_values import ForgottenFavorite
from spotify_manager.domain.listening_values import ListeningChange
from spotify_manager.domain.listening_values import ListeningComparison
from spotify_manager.domain.listening_values import ListeningDiscoveries
from spotify_manager.domain.listening_values import ListeningQuery
from spotify_manager.domain.listening_values import ListeningRediscovery


@dataclass
class _ArtistDates:
    first: date
    days: set[date] = field(default_factory=set)

    def add(self, day: date) -> None:
        self.first = min(self.first, day)
        self.days.add(day)

    def returned(self, window: int) -> bool:
        for day in self.days:
            if self.first < day <= self.first + timedelta(days=window):
                return True
        return False


@dataclass
class _Cohort:
    artists: int = 0
    eligible: Counter[int] = field(default_factory=Counter)
    returned: Counter[int] = field(default_factory=Counter)

    def add(self, artist: _ArtistDates, through: date) -> None:
        self.artists += 1
        for window in (7, 30, 90):
            if artist.first + timedelta(days=window) > through:
                continue
            self.eligible[window] += 1
            self.returned[window] += int(artist.returned(window))

    def result(self, month: str) -> DiscoveryCohort:
        return DiscoveryCohort(
            month,
            self.artists,
            self.eligible[7],
            self.returned[7],
            self.eligible[30],
            self.returned[30],
            self.eligible[90],
            self.returned[90],
        )


def listening_discoveries(
    plays: tuple[ArtistPlay, ...], query: ListeningQuery, last_ms: int | None
) -> ListeningDiscoveries:
    """Evaluate first-observed cohorts against complete follow-up calendar days.

    Args:
        plays: Full pre-cutoff history; date/rhythm filtering must not reset firsts.
        query: Visible cohort interval, timezone, and optional artist selection.
        last_ms: Source's last recorded instant.

    Returns:
        Monthly cohorts with incomplete follow-up excluded from denominators.
    """
    if last_ms is None:
        return ListeningDiscoveries((), None)
    complete_through = local_instant(last_ms, query.timezone).date() - timedelta(days=1)
    through = min(query.end, complete_through)
    artists = _artist_dates(plays, query.timezone)
    cohorts: dict[str, _Cohort] = {}
    for artist in artists.values():
        if not query.start <= artist.first <= query.end:
            continue
        month = artist.first.isoformat()[:7]
        cohorts.setdefault(month, _Cohort()).add(artist, through)
    results = []
    for month in sorted(cohorts):
        results.append(cohorts[month].result(month))
    return ListeningDiscoveries(tuple(results), through)


def _artist_dates(
    plays: tuple[ArtistPlay, ...], timezone: str
) -> dict[str, _ArtistDates]:
    result: dict[str, _ArtistDates] = {}
    for play in plays:
        day = local_instant(play.timestamp_ms, timezone).date()
        result.setdefault(play.artist_key, _ArtistDates(day)).add(day)
    return result


def forgotten_favorites(
    lifetimes: tuple[EntityLifetime, ...],
    query: ListeningQuery,
    thresholds: tuple[int, int],
) -> ListeningRediscovery:
    """Select substantial recorded favorites with a minimum inactivity gap.

    Args:
        lifetimes: Full entity history through the selected analysis end.
        query: Analysis date and display timezone.
        thresholds: Inclusive minimum play count and minimum calendar-day gap.

    Returns:
        At most 100 entries ordered by historical plays, then inactivity and key.
    """
    minimum_plays, minimum_gap = thresholds
    result = []
    for entity in lifetimes:
        day = local_instant(entity.last_ms, query.timezone).date()
        gap = (query.end - day).days
        if entity.plays >= minimum_plays and gap >= minimum_gap:
            result.append(ForgottenFavorite(entity, gap))
    result.sort(key=_forgotten_order)
    return ListeningRediscovery(
        tuple(result[:100]), len(result), query.end, minimum_plays, minimum_gap
    )


def _forgotten_order(item: ForgottenFavorite) -> tuple[int, int, str]:
    return -item.entity.plays, -item.days_since_last, item.entity.key


def compare_listening(
    periods: tuple[tuple[EntityLifetime, ...], tuple[EntityLifetime, ...]],
    query: ListeningQuery,
    first_ms: int | None,
) -> ListeningComparison:
    """Compare top artist shares across equal calendar-length selections.

    Args:
        periods: Previous and current period artist counts.
        query: Current period and filters.
        first_ms: Earliest source observation, for previous-period coverage.

    Returns:
        Top 15 artists by combined count with explicit previous coverage.
    """
    previous, current = periods
    duration = timedelta(days=(query.end - query.start).days + 1)
    start, end = query.start - duration, query.start - timedelta(days=1)
    previous_total = sum(item.plays for item in previous)
    current_total = sum(item.plays for item in current)
    items = _changes(previous, current, (previous_total, current_total))
    covered = (
        first_ms is not None and local_instant(first_ms, query.timezone).date() < start
    )
    return ListeningComparison(
        start, end, previous_total, current_total, covered, items
    )


def _changes(
    previous: tuple[EntityLifetime, ...],
    current: tuple[EntityLifetime, ...],
    totals: tuple[int, int],
) -> tuple[ListeningChange, ...]:
    previous_counts = {item.key: item.plays for item in previous}
    current_counts = {item.key: item.plays for item in current}
    names = {item.key: item.name for item in previous + current}
    combined: Counter[str] = Counter(previous_counts)
    combined.update(current_counts)
    result = []
    for key, _count in combined.most_common(15):
        old, new = previous_counts.get(key, 0), current_counts.get(key, 0)
        result.append(
            ListeningChange(
                key,
                names[key],
                old,
                new,
                old / totals[0] if totals[0] else 0,
                new / totals[1] if totals[1] else 0,
            )
        )
    return tuple(result)
