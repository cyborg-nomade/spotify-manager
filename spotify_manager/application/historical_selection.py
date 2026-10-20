"""Select historical tracks with explicit history, calendar and random boundaries."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from spotify_manager.application.historical_values import BlastFromPastBatch
from spotify_manager.application.historical_values import BlastFromPastError
from spotify_manager.application.historical_values import DailyMindRadioBatch
from spotify_manager.application.historical_values import LastFmExportError
from spotify_manager.application.ports.history import HistoricalInputs
from spotify_manager.domain.history import Scrobble
from spotify_manager.domain.history import anniversary_dates
from spotify_manager.domain.history import eligible_dates
from spotify_manager.domain.history import select_scrobble


type HistoryByDate = dict[date, list[Scrobble]]


@dataclass(frozen=True)
class BlastSelection:
    """Select the Friday routine's dates before applying its timestamp pagination.

    Args:
        inputs: File, calendar settings and external random observations.
        progress: Present existing progress messages.
    """

    inputs: HistoricalInputs
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
        history = self.inputs.history()
        cutoff = self.inputs.cutoff()
        available = eligible_dates(history, self.inputs.first_date, cutoff)
        _validate_population(count, available, cutoff)
        self.progress("Requesting unique date indexes from Random.org")
        indexes = self.inputs.random(len(available), count)
        self.progress("Applying Last.fm pagination rules")
        selections = []
        for index in indexes.indexes:
            day = available[index]
            selections.append(
                select_scrobble(
                    day,
                    index,
                    history[day],
                    indexes.generated_at,
                    self.inputs.page_size,
                )
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
        inputs: File, calendar settings and external random observations.
        progress: Present existing progress messages.
    """

    inputs: HistoricalInputs
    progress: Callable[[str], None]

    def run(self) -> DailyMindRadioBatch:
        """Choose one play from each populated anniversary date.

        Returns:
            All target dates, missing dates and selected plays in original order.

        Raises:
            LastFmExportError: The history has no date buckets.
        """
        self.progress("Loading Last.fm scrobbles")
        history = self.inputs.history()
        if not history:
            raise LastFmExportError(
                "The Last.fm export does not contain any scrobbles."
            )
        current = self.inputs.today()
        targets = anniversary_dates(
            current, min(day.year for day in history), self.inputs.anniversary_interval
        )
        populated, missing = _partition_dates(targets, history)
        if not populated:
            return DailyMindRadioBatch(None, targets, missing, ())
        self.progress("Requesting a selection timestamp from Random.org")
        generated_at = self.inputs.timestamp()
        self.progress("Applying Last.fm pagination rules")
        indexes = {day: index for index, day in enumerate(targets)}
        selections = []
        for day in populated:
            selections.append(
                select_scrobble(
                    day, indexes[day], history[day], generated_at, self.inputs.page_size
                )
            )
        return DailyMindRadioBatch(generated_at, targets, missing, tuple(selections))
