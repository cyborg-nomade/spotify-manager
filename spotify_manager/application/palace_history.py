"""Gather Palace history before the original cutoff and Random.org observations."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from datetime import datetime

from spotify_manager.application.historical_values import LastFmExportError
from spotify_manager.application.historical_values import RandomIndexSet
from spotify_manager.application.historical_values import RandomOrgError
from spotify_manager.application.palace_values import PalaceOfMemoryDataError
from spotify_manager.application.palace_values import PalaceOfMemoryError
from spotify_manager.domain.history import Scrobble
from spotify_manager.domain.palace_history import dated_rankings
from spotify_manager.domain.palace_history import selected_albums
from spotify_manager.domain.palace_values import HistoricalAlbumSelection


@dataclass(frozen=True)
class PalaceHistory:
    """Retain original history, calendar, random and presentation read boundaries.

    Args:
        history: Original complete history reader.
        cutoff: Original effective cutoff resolved after reading history.
        random: Original caller-owned Random.org or custom index reader.
        progress: Original optional progress delivery adapter.
        first: Original earliest eligible date.
    """

    history: Callable[[], dict[date, list[Scrobble]]]
    cutoff: Callable[[], date]
    random: Callable[[int, int], RandomIndexSet]
    progress: Callable[[str], None]
    first: date

    def run(
        self, count: int
    ) -> tuple[datetime, date, int, tuple[HistoricalAlbumSelection, ...]]:
        """Gather original rankings before requesting ordered unique date indexes.

        Args:
            count: Original requested selection size, retaining custom-reader tolerance.

        Returns:
            Original timestamp, cutoff, population and complete selected albums.

        Raises:
            PalaceOfMemoryDataError: History cannot load or the population is too small.
            PalaceOfMemoryError: The original random reader rejects its request.
            IndexError: The original custom reader returns an out-of-range index.
        """
        self.progress("Loading Last.fm album history")
        history = self._history()
        cutoff = self.cutoff()
        rankings = dated_rankings(history, self.first, cutoff)
        if count > len(rankings):
            raise PalaceOfMemoryDataError(
                f"Only {len(rankings)} album-bearing dates are available "
                f"through {cutoff.isoformat()}."
            )
        self.progress("Requesting five unique date indexes from Random.org")
        indexes = self._random(len(rankings), count)
        selected = selected_albums(rankings, indexes.indexes, indexes.generated_at)
        return indexes.generated_at, cutoff, len(rankings), selected

    def _history(self) -> dict[date, list[Scrobble]]:
        try:
            return self.history()
        except LastFmExportError as exc:
            raise PalaceOfMemoryDataError(str(exc)) from exc

    def _random(self, population: int, count: int) -> RandomIndexSet:
        try:
            return self.random(population, count)
        except (ValueError, RandomOrgError) as exc:
            raise PalaceOfMemoryError(str(exc)) from exc
