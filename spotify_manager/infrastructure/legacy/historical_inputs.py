"""Read original history and calendar inputs without selecting business rules."""

from dataclasses import dataclass
from datetime import date
from datetime import datetime
from pathlib import Path

from spotify_manager.application.historical_values import RandomIndexSet
from spotify_manager.domain.history import Scrobble
from spotify_manager.routines import blast_from_past as blast
from spotify_manager.routines import daily_mind_radio as radio
from spotify_manager.routines.blast_from_past import fetch_random_indexes
from spotify_manager.routines.blast_from_past import fetch_random_timestamp


@dataclass(frozen=True)
class LegacyHistoricalInputs:
    """Own external readers and the date override for one historical selection.

    Args:
        path: Original history export.
        date_override: Optional effective calendar date.
        index_reader: Caller-selected external random-index reader.
        timestamp_reader: Caller-selected external timestamp reader.
    """

    path: Path
    date_override: date | None
    index_reader: blast.RandomIndexReader = fetch_random_indexes
    timestamp_reader: radio.RandomTimestampReader = fetch_random_timestamp

    @property
    def first_date(self) -> date:
        """Return the earliest-date setting at its original observation boundary.

        Returns:
            Inclusive earliest eligible local date.
        """
        return blast.FIRST_ELIGIBLE_DATE

    @property
    def page_size(self) -> int:
        """Return the original pagination setting when selection reaches it.

        Returns:
            Original configured Last.fm page size.
        """
        return blast.LASTFM_PAGE_SIZE

    @property
    def anniversary_interval(self) -> int:
        """Return the original anniversary spacing when selecting dates.

        Returns:
            Configured anniversary spacing in years.
        """
        return radio.ANNIVERSARY_INTERVAL_YEARS

    def history(self) -> dict[date, list[Scrobble]]:
        """Load complete dated buckets through the original concrete file reader.

        Returns:
            Existing buckets in original order.

        Raises:
            LastFmExportError: The original export cannot be read.
        """
        from spotify_manager.routines.blast_from_past import load_scrobbles_by_date

        return load_scrobbles_by_date(self.path)

    def cutoff(self) -> date:
        """Observe the original Friday cutoff after reading history.

        Returns:
            Original inclusive local-date cutoff.
        """
        from spotify_manager.routines.blast_from_past import friday_track_cutoff

        return friday_track_cutoff(self.date_override)

    def today(self) -> date:
        """Observe the caller override or original local clock after history.

        Returns:
            Original effective local date.
        """
        return self.date_override or radio.datetime.now(blast.SCROBBLE_TIMEZONE).date()

    def random(self, population: int, count: int) -> RandomIndexSet:
        """Invoke the caller's external index reader once.

        Args:
            population: Eligible date count.
            count: Original requested count.

        Returns:
            Original unmodified random response.
        """
        return self.index_reader(population, count)

    def timestamp(self) -> datetime:
        """Read one external timestamp for the complete anniversary selection.

        Returns:
            Original shared external selection timestamp.
        """
        return self.timestamp_reader()
