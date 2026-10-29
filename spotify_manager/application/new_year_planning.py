"""Plan all original retrospective markers before any playlist mutation."""

from dataclasses import dataclass
from datetime import tzinfo

from spotify_manager.application.history_refresh import HistoryRefresh
from spotify_manager.application.new_year_resolution import AnnualResolution
from spotify_manager.application.new_year_values import NewYearError
from spotify_manager.application.new_year_values import RetrospectivePlan
from spotify_manager.application.ports.annual import AnnualPlaylist
from spotify_manager.application.ports.runtime import Messages
from spotify_manager.domain.annual_history import YearEntry
from spotify_manager.domain.annual_history import rank_year
from spotify_manager.domain.annual_selection import existing_primary_marker
from spotify_manager.domain.catalog import PlaylistTrack


@dataclass(frozen=True)
class AnnualPlanning:
    """Bind original full history refresh, current sources and marker resolution.

    Args:
        history: Original full rebuild, retaining preview publication semantics.
        username: Original expected canonical history account.
        catalog: Named external catalog observations used by this stage.
        resolution: Original track, album and primary artist lookup boundaries.
        output: Original visible planning presenter.
        timezone: Original annual calendar timezone.
    """

    history: HistoryRefresh
    username: str | None
    catalog: AnnualPlaylist
    resolution: AnnualResolution
    output: Messages
    timezone: tzinfo

    async def run(
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
        self.output.echo(
            "Rebuilding complete Last.fm history before ranking the previous year"
        )
        history = (await self.history.run(self.username, preview, True)).history
        ranked = rank_year(history, year, self.timezone)
        if not ranked["tracks"]:
            raise NewYearError(f"No scrobbles found for {year}.")
        obsession_uris = []
        for track in await self.catalog.playlist(obsessions):
            obsession_uris.append(track.uri)
        plan: RetrospectivePlan = {
            "tracks": ranked["tracks"][:50],
            "albums": ranked["albums"][:20],
            "artists": ranked["artists"][:5],
            "destinations": destinations,
            "obsessions": obsession_uris,
        }
        await self._tracks(plan["tracks"])
        await self._albums(plan["albums"])
        memory = await self.catalog.playlist(destinations["memory"])
        await self._artists(plan["artists"], ranked["tracks"], memory)
        return plan

    async def _tracks(self, items: list[YearEntry]) -> None:
        for item in items:
            self.output.echo(
                f"Top track: {item['artist']} — {item['name']} ({item['scrobbles']})"
            )
            item["uri"] = await self.resolution.track(item)

    async def _albums(self, items: list[YearEntry]) -> None:
        for item in items:
            self.output.echo(
                f"Top album: {item['artist']} — {item['name']} ({item['scrobbles']})"
            )
            item["uri"] = await self.resolution.album_marker(item)

    async def _artists(
        self,
        items: list[YearEntry],
        ranked: list[YearEntry],
        memory: tuple[PlaylistTrack, ...],
    ) -> None:
        for item in items:
            self.output.echo(f"Top artist: {item['artist']} ({item['scrobbles']})")
            identity = await self.resolution.artist_identity(item)
            item["artist_id"] = identity
            marker = existing_primary_marker(memory, identity)
            item["uri"] = (
                marker
                if marker is not None
                else (await self._marker(item, ranked, identity))
            )

    async def _marker(
        self, artist: YearEntry, ranked: list[YearEntry], identity: str
    ) -> str:
        for candidate in ranked:
            if candidate["artist"].casefold() != artist["artist"].casefold():
                continue
            uri = await self.resolution.track(candidate)
            if (await self.resolution.catalog.primary(uri)) == identity:
                return uri
        raise NewYearError(f"No primary-artist track for {artist['artist']}.")
