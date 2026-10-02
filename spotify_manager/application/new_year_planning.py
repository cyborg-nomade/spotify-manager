"""Plan all original retrospective markers before any playlist mutation."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import tzinfo

from spotify_manager.application.new_year_resolution import AnnualResolution
from spotify_manager.application.new_year_values import NewYearError
from spotify_manager.application.new_year_values import RetrospectivePlan
from spotify_manager.domain.annual_history import YearEntry
from spotify_manager.domain.annual_history import rank_year
from spotify_manager.domain.annual_selection import existing_primary_marker
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.history import Scrobble


@dataclass(frozen=True)
class AnnualPlanning:
    """Bind original full history refresh, current sources and marker resolution.

    Args:
        history: Original full rebuild, retaining preview publication semantics.
        playlist: Original complete fresh playlist marker facts.
        resolution: Original track, album and primary artist lookup boundaries.
        echo: Original visible planning presenter.
        timezone: Original annual calendar timezone.
    """

    history: Callable[[bool], tuple[Scrobble, ...]]
    playlist: Callable[[str], tuple[PlaylistTrack, ...]]
    resolution: AnnualResolution
    echo: Callable[[str], None]
    timezone: tzinfo

    def run(
        self, year: int, preview: bool, destinations: dict[str, str], obsessions: str
    ) -> RetrospectivePlan:
        """Refresh and resolve the complete original top fifty/twenty/five plan.

        Args:
            year: Original completed calendar year.
            preview: Original history rebuild persistence behavior.
            destinations: Original exact destination settings.
            obsessions: Original validated annual source identity.

        Returns:
            Original complete resolved plan and uncapped Obsessions membership.

        Raises:
            NewYearError: Annual history or an original marker cannot be resolved.
        """
        self.echo(
            "Rebuilding complete Last.fm history before ranking the previous year"
        )
        ranked = rank_year(self.history(preview), year, self.timezone)
        if not ranked["tracks"]:
            raise NewYearError(f"No scrobbles found for {year}.")
        plan: RetrospectivePlan = {
            "tracks": ranked["tracks"][:50],
            "albums": ranked["albums"][:20],
            "artists": ranked["artists"][:5],
            "destinations": destinations,
            "obsessions": [track.uri for track in self.playlist(obsessions)],
        }
        self._tracks(plan["tracks"])
        self._albums(plan["albums"])
        memory = self.playlist(destinations["memory"])
        self._artists(plan["artists"], ranked["tracks"], memory)
        return plan

    def _tracks(self, items: list[YearEntry]) -> None:
        for item in items:
            self.echo(
                f"Top track: {item['artist']} — {item['name']} ({item['scrobbles']})"
            )
            item["uri"] = self.resolution.track(item)

    def _albums(self, items: list[YearEntry]) -> None:
        for item in items:
            self.echo(
                f"Top album: {item['artist']} — {item['name']} ({item['scrobbles']})"
            )
            item["uri"] = self.resolution.album_marker(item)

    def _artists(
        self,
        items: list[YearEntry],
        ranked: list[YearEntry],
        memory: tuple[PlaylistTrack, ...],
    ) -> None:
        for item in items:
            self.echo(f"Top artist: {item['artist']} ({item['scrobbles']})")
            identity = self.resolution.artist_identity(item)
            item["artist_id"] = identity
            marker = existing_primary_marker(memory, identity)
            item["uri"] = (
                marker if marker is not None else self._marker(item, ranked, identity)
            )

    def _marker(self, artist: YearEntry, ranked: list[YearEntry], identity: str) -> str:
        for candidate in ranked:
            if candidate["artist"].casefold() != artist["artist"].casefold():
                continue
            uri = self.resolution.track(candidate)
            if self.resolution.primary(uri) == identity:
                return uri
        raise NewYearError(f"No primary-artist track for {artist['artist']}.")
