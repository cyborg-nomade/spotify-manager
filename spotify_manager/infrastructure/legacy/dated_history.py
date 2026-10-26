"""Read dated history, its local cutoff and caller-owned random observations."""

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from spotify_manager.application.historical_values import RandomIndexSet
from spotify_manager.application.ports.runtime import RandomIndexes
from spotify_manager.domain.history import Scrobble


@dataclass(frozen=True)
class LegacyDatedHistory:
    """Own history, calendar and external random observations.

    Args:
        path: Original history export.
        date_override: Optional effective local date.
        index_reader: Original caller-selected external index reader.
    """

    path: Path
    date_override: date | None
    index_reader: RandomIndexes

    def history(self) -> dict[date, list[Scrobble]]:
        """Read complete dated history through the original concrete file helper.

        Returns:
            Complete dated scrobble buckets in original encounter order.
        """
        from spotify_manager.routines.blast_from_past import load_scrobbles_by_date

        return load_scrobbles_by_date(self.path)

    def cutoff(self) -> date:
        """Observe the original effective cutoff after loading history.

        Returns:
            Original inclusive local-date cutoff.
        """
        from spotify_manager.routines.palace_of_memory import palace_cutoff

        return palace_cutoff(self.date_override)

    def random(self, population: int, count: int) -> RandomIndexSet:
        """Read original unique indexes and their shared timestamp.

        Args:
            population: Eligible date count.
            count: Requested selection count.

        Returns:
            Original unmodified random response.
        """
        return self.index_reader.sample(population, count)
