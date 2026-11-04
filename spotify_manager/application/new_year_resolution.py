"""Resolve original annual tracks, albums and mapped primary artist markers."""

from dataclasses import dataclass

from spotify_manager.application.manual_album_matching import ManualAlbumMatching
from spotify_manager.application.manual_track_matching import ManualTrackMatching
from spotify_manager.application.new_year_values import NewYearError
from spotify_manager.application.ports.annual import AnnualLookup
from spotify_manager.application.ports.runtime import Messages
from spotify_manager.domain.annual_history import YearEntry
from spotify_manager.domain.annual_selection import selected_track
from spotify_manager.domain.golden_markers import exact_artists
from spotify_manager.domain.history import Scrobble
from spotify_manager.domain.palace_values import SpotifyAlbum


@dataclass(frozen=True)
class AnnualResolution:
    """Bind original caller-owned search and marker facts.

    Args:
        catalog: Named external catalog observations used by this stage.
        manual: Optional explicit track matching stage.
        albums: Optional explicit album matching stage.
        output: Optional presenter for rejected artist-marker choices.
    """

    catalog: AnnualLookup
    manual: ManualTrackMatching | None = None
    albums: ManualAlbumMatching | None = None
    output: Messages | None = None

    async def track(self, item: YearEntry) -> str | None:
        """Select the original first exact or first qualified track marker.

        Args:
            item: Original ranked display artist/title facts.

        Returns:
            Selected playable URI, or none after an explicit no-match choice.

        Raises:
            NewYearError: The original search has no match.
        """
        if self.manual is not None and item.get("dropped"):
            return None
        if self.manual is not None and "uri" in item:
            return item["uri"]
        candidate = selected_track(await self.catalog.search(item))
        if candidate is None and self.manual is not None:
            candidate = await self.manual.run(
                Scrobble(item["name"], item["artist"], "", 0)
            )
            return candidate.uri if candidate is not None else None
        if candidate is None:
            raise NewYearError(
                f"No Spotify track match: {item['artist']} — {item['name']}"
            )
        return candidate.uri

    async def album_marker(self, item: YearEntry) -> str | None:
        """Resolve the original release before reading its complete first marker.

        Args:
            item: Original ranked artist/release display facts.

        Returns:
            Selected first marker URI, or none after an explicit no-match choice.

        Raises:
            NewYearError: The original album lookup has no match.
        """
        album = await self.catalog.album(item["artist"], item["name"])
        if album is None and self.albums is not None:
            chosen = await self.albums.run(
                Scrobble("", item["artist"], item["name"], 0)
            )
            if chosen is None:
                return None
            album = SpotifyAlbum(
                chosen.spotify_id,
                chosen.uri,
                ", ".join(chosen.artists),
                chosen.album,
                False,
                0.0,
            )
        if album is None:
            raise NewYearError(
                f"No Spotify album match: {item['artist']} — {item['name']}"
            )
        return (await self.catalog.first(album)).uri

    async def artist_identity(self, item: YearEntry) -> str | None:
        """Resolve a unique artist or explicitly choose its primary-artist marker.

        Args:
            item: Original ranked display artist facts.

        Returns:
            Mapped primary artist identity, or none after explicit rejection.

        Raises:
            NewYearError: The original mapping is cancelled or has no match.
        """
        if self.manual is not None:
            candidates = exact_artists(
                item["artist"], await self.catalog.artist_candidates(item["artist"])
            )
            if len(candidates) == 1:
                return candidates[0].spotify_id
            return await self._manual_artist(item)
        artist = await self.catalog.artist(item["artist"])
        if artist is None:
            raise NewYearError(f"No Spotify artist match: {item['artist']}")
        return artist.spotify_id

    async def _manual_artist(self, item: YearEntry) -> str | None:
        assert self.manual is not None
        chosen = await self.manual.run(Scrobble("", item["artist"], "", 0))
        if chosen is None:
            return None
        identity = await self.catalog.primary(chosen.uri)
        if not isinstance(identity, str) or not identity:
            raise NewYearError("The selected artist marker has no primary artist.")
        item["uri"] = chosen.uri
        return identity

    async def marker(self, item: YearEntry, identity: str) -> str | None:
        """Choose a fallback marker while retaining the mapped primary-artist rule.

        Args:
            item: Ranked historical artist whose ranked tracks lack a marker.
            identity: Previously accepted Spotify artist identity.

        Returns:
            Accepted primary-artist marker or an explicit no-match outcome.

        Raises:
            RuntimeError: Invocation cancellation is requested.
        """
        assert self.manual is not None
        while True:
            chosen = await self.manual.run(Scrobble("", item["artist"], "", 0))
            if chosen is None:
                return None
            if await self.catalog.primary(chosen.uri) == identity:
                return chosen.uri
            self._rejected_marker()

    def _rejected_marker(self) -> None:
        if self.output is not None:
            self.output.echo(
                "Different primary artist; choose another marker or No match."
            )
