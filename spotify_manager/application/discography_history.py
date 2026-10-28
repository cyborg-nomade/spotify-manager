"""Gather original dated artist history before cutoff and random-source reads."""

from dataclasses import dataclass
from datetime import date
from typing import Protocol

from spotify_manager.application.discography_values import DiscographyCancelledError
from spotify_manager.application.discography_values import DiscographyError
from spotify_manager.application.historical_values import LastFmExportError
from spotify_manager.application.historical_values import RandomIndexSet
from spotify_manager.application.historical_values import RandomOrgError
from spotify_manager.application.ports.runtime import Messages
from spotify_manager.application.something_old_values import SomethingOldError
from spotify_manager.domain.discography_history import dated_artists
from spotify_manager.domain.discography_history import selected_artist
from spotify_manager.domain.discography_values import HistoricalArtistSelection
from spotify_manager.domain.discography_values import QueueArtist
from spotify_manager.domain.golden_selection import SpotifyArtistCandidate
from spotify_manager.domain.history import Scrobble


class HistoricalArtistCatalog(Protocol):
    """Read the original exact Spotify artist mapping and ambiguity interaction."""

    async def resolve(self, name: str) -> SpotifyArtistCandidate | None:
        """Read an exact artist mapping.

        Args:
            name: Historical artist display name.

        Returns:
            Accepted identity or cancellation.
        """


class DatedHistory(Protocol):
    """Read complete history before observing its cutoff and random source."""

    async def history(self) -> dict[date, list[Scrobble]]:
        """Return the complete dated history buckets.

        Returns:
            Complete dated scrobble buckets in original encounter order.
        """

    def cutoff(self) -> date:
        """Observe the original inclusive historical cutoff.

        Returns:
            Original inclusive local-date cutoff.
        """

    async def random(self, population: int, count: int) -> RandomIndexSet:
        """Read original ordered indexes and shared timestamp.

        Args:
            population: Eligible populated-date count.
            count: Original requested selection count.

        Returns:
            Original unmodified random-source response.
        """


async def resolve_historical(
    selection: HistoricalArtistSelection,
    catalog: HistoricalArtistCatalog,
) -> QueueArtist:
    """Translate original exact artist mapping and cancellation into batch facts.

    Args:
        selection: Original complete historical artist choice.
        catalog: Original exact Spotify artist mapping integration.

    Returns:
        Original complete Memory Lane candidate.

    Raises:
        DiscographyError: Original artist mapping fails.
        DiscographyCancelledError: Original mapping is cancelled.
    """
    try:
        resolved = await catalog.resolve(selection.artist.name)
    except SomethingOldError as exc:
        raise DiscographyError(str(exc)) from exc
    if resolved is None:
        raise DiscographyCancelledError(
            "Discography planning cancelled during historical artist mapping."
        )
    return QueueArtist(resolved.spotify_id, resolved.name, "memory_lane")


@dataclass(frozen=True)
class DiscographyArtistMapping:
    """Translate historical mapping through the named application operation.

    Args:
        catalog: Original exact artist observation and ambiguity interaction.
    """

    catalog: HistoricalArtistCatalog

    async def resolve(self, selection: HistoricalArtistSelection) -> QueueArtist:
        """Resolve a historical candidate with the original error translation.

        Args:
            selection: Original complete historical artist selection.

        Returns:
            Accepted Memory Lane candidate.
        """
        return await resolve_historical(selection, self.catalog)


@dataclass(frozen=True)
class DiscographyHistory:
    """Bind original history, calendar, random and progress observations.

    Args:
        source: History, calendar and external random observations.
        progress: Original optional progress delivery.
        first: Original earliest eligible date.
    """

    source: DatedHistory
    progress: Messages
    first: date

    async def run(self) -> HistoricalArtistSelection:
        """Request one historical date and retain original custom-reader tolerance.

        Returns:
            Original complete historical artist facts.

        Raises:
            DiscographyError: History is unavailable, empty or random reading fails.
            IndexError: The original reader returns no index or an invalid index.
        """
        self.progress.echo("Memory Lane is empty; loading Last.fm artist history")
        history = await self._history()
        cutoff = self.source.cutoff()
        rankings = dated_artists(history, self.first, cutoff)
        if not rankings:
            raise DiscographyError(
                "No artist-bearing Last.fm dates are available through "
                f"{cutoff.isoformat()}."
            )
        self.progress.echo("Requesting a historical date from Random.org")
        indexes = await self._random(len(rankings))
        return selected_artist(
            rankings, cutoff, indexes.indexes[0], indexes.generated_at
        )

    async def _history(self) -> dict[date, list[Scrobble]]:
        try:
            return await self.source.history()
        except LastFmExportError as exc:
            raise DiscographyError(str(exc)) from exc

    async def _random(self, population: int) -> RandomIndexSet:
        try:
            return await self.source.random(population, 1)
        except (ValueError, RandomOrgError) as exc:
            raise DiscographyError(str(exc)) from exc
