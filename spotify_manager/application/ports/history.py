"""External observations required by historical selection and matching."""

from datetime import date
from datetime import datetime
from typing import Protocol

from spotify_manager.application.historical_values import RandomIndexSet
from spotify_manager.domain.history import Scrobble
from spotify_manager.domain.history_matching import PlaylistState
from spotify_manager.domain.history_matching import SpotifyTrackMatch


class HistoricalInputs(Protocol):
    """Read history, calendar settings and external random observations."""

    @property
    def first_date(self) -> date:
        """Return the inclusive earliest eligible date.

        Returns:
            Inclusive earliest eligible local date.
        """

    @property
    def page_size(self) -> int:
        """Return the original Last.fm pagination size.

        Returns:
            Original configured Last.fm page size.
        """

    @property
    def anniversary_interval(self) -> int:
        """Return the configured anniversary spacing in years.

        Returns:
            Configured anniversary spacing in years.
        """

    def history(self) -> dict[date, list[Scrobble]]:
        """Return complete dated history in original bucket order.

        Returns:
            Complete dated scrobble buckets in original encounter order.
        """

    def cutoff(self) -> date:
        """Observe the inclusive Friday cutoff after loading history.

        Returns:
            Original inclusive local-date cutoff.
        """

    def today(self) -> date:
        """Observe the effective local anniversary date.

        Returns:
            Original effective local date.
        """

    def random(self, population: int, count: int) -> RandomIndexSet:
        """Read ordered random indexes and their shared timestamp.

        Args:
            population: Eligible date count.
            count: Requested selection count.

        Returns:
            Original unmodified random-source response.
        """

    def timestamp(self) -> datetime:
        """Read one external timestamp for all populated anniversaries.

        Returns:
            Original shared external selection timestamp.
        """


class HistoricalMatches(Protocol):
    """Search Spotify and read liked status after all match groups are complete."""

    def search(self, scrobble: Scrobble) -> tuple[SpotifyTrackMatch, ...]:
        """Read candidates for a selected play.

        Args:
            scrobble: Original selected play.

        Returns:
            Candidates in search encounter order.
        """

    def liked(self, groups: list[tuple[SpotifyTrackMatch, ...]]) -> set[str]:
        """Read liked membership after all searches finish.

        Args:
            groups: Ordered complete candidate groups.

        Returns:
            Currently liked identities.
        """


class HistoricalPlaylist(Protocol):
    """Read a destination and append accepted matches in their original order."""

    def read(self) -> PlaylistState:
        """Return the original raw length and represented identities.

        Returns:
            Original complete destination length and represented identities.
        """

    def append(self, matches: list[SpotifyTrackMatch]) -> None:
        """Append pending matches through the existing batching boundary.

        Args:
            matches: Unique accepted matches.
        """


class HistoricalMatchCatalog(HistoricalMatches, Protocol):
    """Expose the matching threshold at the original resolution boundary."""

    @property
    def album_threshold(self) -> float:
        """Return the current album qualification threshold.

        Returns:
            Current configured album qualification threshold.
        """
