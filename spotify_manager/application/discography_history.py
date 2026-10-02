"""Gather original dated artist history before cutoff and random-source reads."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from spotify_manager.application.discography_values import DiscographyCancelledError
from spotify_manager.application.discography_values import DiscographyError
from spotify_manager.application.historical_values import LastFmExportError
from spotify_manager.application.historical_values import RandomIndexSet
from spotify_manager.application.historical_values import RandomOrgError
from spotify_manager.application.something_old_values import SomethingOldError
from spotify_manager.domain.discography_history import dated_artists
from spotify_manager.domain.discography_history import selected_artist
from spotify_manager.domain.discography_values import HistoricalArtistSelection
from spotify_manager.domain.discography_values import QueueArtist
from spotify_manager.domain.golden_selection import SpotifyArtistCandidate
from spotify_manager.domain.history import Scrobble


def resolve_historical(
    selection: HistoricalArtistSelection,
    resolve: Callable[[str], SpotifyArtistCandidate | None],
) -> QueueArtist:
    """Translate original exact artist mapping and cancellation into batch facts.

    Args:
        selection: Original complete historical artist choice.
        resolve: Original exact Spotify artist mapping interaction.

    Returns:
        Original complete Memory Lane candidate.

    Raises:
        DiscographyError: Original artist mapping fails.
        DiscographyCancelledError: Original mapping is cancelled.
    """
    try:
        resolved = resolve(selection.artist.name)
    except SomethingOldError as exc:
        raise DiscographyError(str(exc)) from exc
    if resolved is None:
        raise DiscographyCancelledError(
            "Discography planning cancelled during historical artist mapping."
        )
    return QueueArtist(resolved.spotify_id, resolved.name, "memory_lane")


@dataclass(frozen=True)
class DiscographyHistory:
    """Bind original history, calendar, random and progress observations.

    Args:
        history: Original complete dated history reader.
        cutoff: Original effective cutoff resolved after history.
        random: Original random-source or custom reader.
        progress: Original optional progress delivery.
        first: Original earliest eligible date.
    """

    history: Callable[[], dict[date, list[Scrobble]]]
    cutoff: Callable[[], date]
    random: Callable[[int, int], RandomIndexSet]
    progress: Callable[[str], None]
    first: date

    def run(self) -> HistoricalArtistSelection:
        """Request one historical date and retain original custom-reader tolerance.

        Returns:
            Original complete historical artist facts.

        Raises:
            DiscographyError: History is unavailable, empty or random reading fails.
            IndexError: The original reader returns no index or an invalid index.
        """
        self.progress("Memory Lane is empty; loading Last.fm artist history")
        history = self._history()
        cutoff = self.cutoff()
        rankings = dated_artists(history, self.first, cutoff)
        if not rankings:
            raise DiscographyError(
                "No artist-bearing Last.fm dates are available through "
                f"{cutoff.isoformat()}."
            )
        self.progress("Requesting a historical date from Random.org")
        indexes = self._random(len(rankings))
        return selected_artist(
            rankings, cutoff, indexes.indexes[0], indexes.generated_at
        )

    def _history(self) -> dict[date, list[Scrobble]]:
        try:
            return self.history()
        except LastFmExportError as exc:
            raise DiscographyError(str(exc)) from exc

    def _random(self, population: int) -> RandomIndexSet:
        try:
            return self.random(population, 1)
        except (ValueError, RandomOrgError) as exc:
            raise DiscographyError(str(exc)) from exc
