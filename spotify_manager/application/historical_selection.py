"""Select historical tracks with explicit history, calendar and random boundaries."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from datetime import datetime

from spotify_manager.application.historical_values import BlastFromPastBatch
from spotify_manager.application.historical_values import BlastFromPastError
from spotify_manager.application.historical_values import DailyMindRadioBatch
from spotify_manager.application.historical_values import LastFmExportError
from spotify_manager.application.historical_values import RandomIndexSet
from spotify_manager.domain.history import Scrobble
from spotify_manager.domain.history import ScrobbleSelection


type HistoryByDate = dict[date, list[Scrobble]]
type ScrobbleSelector = Callable[
    [date, int, list[Scrobble], datetime], ScrobbleSelection
]


@dataclass(frozen=True)
class BlastSelection:
    """Select the Friday routine's dates before applying its timestamp pagination.

    Args:
        history: Read the existing local history buckets.
        cutoff: Resolve the effective inclusive historical cutoff.
        eligible: Apply the existing earliest-date and populated-date policy.
        random: Request unique date indexes and their shared timestamp.
        select: Apply the original track-page policy.
        progress: Present existing progress messages.
    """

    history: Callable[[], HistoryByDate]
    cutoff: Callable[[], date]
    eligible: Callable[[HistoryByDate, date], list[date]]
    random: Callable[[int, int], RandomIndexSet]
    select: ScrobbleSelector
    progress: Callable[[str], None]

    def run(self, count: int) -> BlastFromPastBatch:
        """Choose tracks from the random source's original index order.

        Args:
            count: Requested number of populated historical dates.

        Returns:
            Selected batch, cutoff and available-date count.

        Raises:
            BlastFromPastError: Count or available population is invalid.
            IndexError: The random boundary supplies an out-of-range index.
        """
        if count < 1:
            raise BlastFromPastError("Count must be at least 1.")
        self.progress("Loading Last.fm scrobbles")
        history = self.history()
        cutoff = self.cutoff()
        available = self.eligible(history, cutoff)
        _validate_population(count, available, cutoff)
        self.progress("Requesting unique date indexes from Random.org")
        indexes = self.random(len(available), count)
        self.progress("Applying Last.fm pagination rules")
        selections = []
        for index in indexes.indexes:
            day = available[index]
            selections.append(
                self.select(day, index, history[day], indexes.generated_at)
            )
        return BlastFromPastBatch(
            indexes.generated_at, cutoff, len(available), tuple(selections)
        )


def _validate_population(count: int, available: list[date], cutoff: date) -> None:
    if not available:
        raise BlastFromPastError(
            f"No scrobbled dates are available through {cutoff.isoformat()}."
        )
    if count > len(available):
        raise BlastFromPastError(
            f"Count {count} exceeds the {len(available)} available dates."
        )


def _partition_dates(
    dates: tuple[date, ...], history: HistoryByDate
) -> tuple[tuple[date, ...], tuple[date, ...]]:
    populated: list[date] = []
    missing: list[date] = []
    for day in dates:
        if history.get(day):
            populated.append(day)
        else:
            missing.append(day)
    return tuple(populated), tuple(missing)


@dataclass(frozen=True)
class AnniversarySelection:
    """Select anniversary dates without losing indexes for missing history buckets.

    Args:
        history: Read the existing history buckets.
        today: Resolve the effective local date after loading history.
        anniversaries: Apply the original year interval and leap-date policy.
        random: Read one shared timestamp only when a target date is populated.
        select: Apply the existing track-page policy.
        progress: Present existing progress messages.
    """

    history: Callable[[], HistoryByDate]
    today: Callable[[], date]
    anniversaries: Callable[[date, int], tuple[date, ...]]
    random: Callable[[], datetime]
    select: ScrobbleSelector
    progress: Callable[[str], None]

    def run(self) -> DailyMindRadioBatch:
        """Choose one play from each populated anniversary date.

        Returns:
            All target dates, missing dates and selected plays in original order.

        Raises:
            LastFmExportError: The history has no date buckets.
        """
        self.progress("Loading Last.fm scrobbles")
        history = self.history()
        if not history:
            raise LastFmExportError(
                "The Last.fm export does not contain any scrobbles."
            )
        current = self.today()
        targets = self.anniversaries(current, min(day.year for day in history))
        populated, missing = _partition_dates(targets, history)
        if not populated:
            return DailyMindRadioBatch(None, targets, missing, ())
        self.progress("Requesting a selection timestamp from Random.org")
        generated_at = self.random()
        self.progress("Applying Last.fm pagination rules")
        indexes = {day: index for index, day in enumerate(targets)}
        selections = []
        for day in populated:
            selections.append(
                self.select(day, indexes[day], history[day], generated_at)
            )
        return DailyMindRadioBatch(generated_at, targets, missing, tuple(selections))
