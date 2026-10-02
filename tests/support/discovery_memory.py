"""Typed review-planning boundaries over shared in-memory catalog observations."""

from dataclasses import dataclass
from dataclasses import field

from spotify_manager.application.composer_routes import ChoiceCandidate
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.discovery import RankedRelease
from tests.support.assessment_memory import Catalog


@dataclass
class MemoryDiscovery(Catalog):
    """Add discovery catalogs, interaction and event sinks to completion observations.

    Inherited fields retain the scripted completion observations and event log.

    Args:
        catalogs: Scripted ranked catalogs keyed by logical artist ID.
        playlists: Scripted owned works playlists.
        choices: Operator responses, defaulting to the first available option.
    """

    catalogs: dict[str, tuple[RankedRelease, ...]] = field(default_factory=dict)
    playlists: dict[str, tuple[PlaylistTrack, ...]] = field(default_factory=dict)
    choices: list[str] = field(default_factory=list)

    def ranked(self, artist_id: str) -> tuple[RankedRelease, ...]:
        """Observe an artist's ranked discovery catalog.

        Args:
            artist_id: Requested logical artist.

        Returns:
            Scripted original-order catalog, including empty responses.
        """
        self.events.append(("catalog", artist_id))
        return self.catalogs.get(artist_id, ())

    def playlist(self, playlist_id: str) -> tuple[PlaylistTrack, ...]:
        """Observe ordered composer works.

        Args:
            playlist_id: Accepted owned works playlist.

        Returns:
            Scripted markers, including empty responses.
        """
        self.events.append(("playlist", playlist_id))
        return self.playlists.get(playlist_id, ())

    def likes(self, ids: list[str], cache: dict[str, bool]) -> None:
        """Populate missing likes while retaining already accepted observations.

        Args:
            ids: Ordered request, retaining duplicates.
            cache: Mutable shared membership cache.
        """
        self.events.append(("memberships", ids))
        for spotify_id in ids:
            cache.setdefault(spotify_id, self.liked_statuses.get(spotify_id, False))

    def choose(self, artist: str, candidates: tuple[ChoiceCandidate, ...]) -> str:
        """Read the next operator response after original candidate filtering.

        Args:
            artist: Logical artist display name.
            candidates: At most ten best-tier candidates in original order.

        Returns:
            Scripted response, defaulting to the first eligible candidate.
        """
        self.events.append(("choice", (artist, candidates)))
        return self.choices.pop(0) if self.choices else candidates[0].spotify_id

    def event(self, name: str, **details: object) -> None:
        """Observe one original audit boundary.

        Args:
            name: Existing event identifier.
            details: Original ordered structured event fields.
        """
        self.events.append(("audit", (name, details)))

    def release_progress(self, artist: str, completed: int, year: int) -> None:
        """Observe progress presentation immediately before its audit.

        Args:
            artist: Logical artist display name.
            completed: Number of completed release entries.
            year: Current invocation year.
        """
        self.events.append(("message", (artist, completed, year)))
