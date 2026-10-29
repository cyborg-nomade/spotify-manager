"""Original synchronous annual catalog and playlist integration."""

from dataclasses import dataclass
from typing import Literal

from spotify_manager.application.new_year_membership import RetryCall
from spotify_manager.application.ports.spotify_client import SpotifyClient as Spotify
from spotify_manager.domain.annual_history import YearEntry
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.composers import OwnedPlaylist
from spotify_manager.domain.golden_selection import SpotifyArtistCandidate
from spotify_manager.domain.history import Scrobble
from spotify_manager.domain.history_matching import SpotifyTrackMatch
from spotify_manager.domain.palace_values import SpotifyAlbum
from spotify_manager.domain.palace_values import SpotifyFirstTrack
from spotify_manager.infrastructure.legacy.new_year_resources import AnnualResources


@dataclass(frozen=True)
class LegacyAnnualSpotify:
    """Own original SDK requests with the caller's annual retry and state resources.

    Args:
        sp: Caller-owned synchronous Spotify client.
        retry: Effective request retry resolved at the original validation boundary.
    """

    sp: Spotify
    retry: RetryCall

    async def search(self, item: YearEntry) -> tuple[SpotifyTrackMatch, ...]:
        """Search the original artist and title.

        Args:
            item: Ranked display artist and title.

        Returns:
            Qualified matches in encounter order.
        """
        from spotify_manager.routines.blast_from_past import (
            async_search_spotify_matches as search_spotify_matches,
        )

        play = Scrobble(
            artist=item["artist"], track=item["name"], album="", timestamp_ms=0
        )
        return await search_spotify_matches(self.sp, play, self.retry)

    async def album(self, artist: str, name: str) -> SpotifyAlbum | None:
        """Search the original release.

        Args:
            artist: Original artist spelling.
            name: Original release title.

        Returns:
            Original accepted release or no match.
        """
        from spotify_manager.routines.palace_of_memory import (
            async_search_spotify_album as search_spotify_album,
        )

        return await search_spotify_album(self.sp, artist, name, self.retry)

    async def first(self, album: SpotifyAlbum) -> SpotifyFirstTrack:
        """Read the original first playable marker.

        Args:
            album: Accepted release.

        Returns:
            Original playable first marker.
        """
        from spotify_manager.routines.palace_of_memory import (
            async_load_first_track as load_first_track,
        )

        return await load_first_track(self.sp, album, self.retry)

    async def artist(self, name: str) -> SpotifyArtistCandidate | None:
        """Read the exact original artist mapping.

        Args:
            name: Original historical artist label.

        Returns:
            Original mapping or cancellation.
        """
        from spotify_manager.routines.something_old import (
            async_resolve_spotify_artist as resolve_spotify_artist,
        )

        return await resolve_spotify_artist(self.sp, name, None, self.retry)

    async def primary(self, uri: str) -> object:
        """Read the original first credit.

        Args:
            uri: Prospective playable marker.

        Returns:
            Unchecked original primary credit.
        """
        from spotify_manager.routines.new_year import _primary_artist

        return await _primary_artist(self.sp, self.retry, uri)

    async def playlist(self, identity: str) -> tuple[PlaylistTrack, ...]:
        """Read complete current playlist markers.

        Args:
            identity: Source or destination identity.

        Returns:
            Ordered current playable markers.
        """
        from spotify_manager.routines.new_wine import (
            async_load_playlist_tracks as load_playlist_tracks,
        )

        return await load_playlist_tracks(self.sp, identity, self.retry)

    async def create(
        self, name: str, kind: Literal["tracks", "albums"], year: int
    ) -> str:
        """Create the original private annual chart.

        Args:
            name: Original chart name.
            kind: Chart category.
            year: Completed source year.

        Returns:
            Accepted chart identity.
        """
        from spotify_manager.routines.new_year import _create_chart

        return await _create_chart(self.sp, self.retry, name, kind, year)

    async def replace(self, playlist: str, uris: list[str]) -> None:
        """Replace the original chart contents.

        Args:
            playlist: Original chart identity.
            uris: Original rank-ordered marker URIs.
        """
        from spotify_manager.routines.new_year import _replace_chart

        await _replace_chart(self.sp, self.retry, playlist, uris)

    async def append(self, playlist: str, uris: list[str], top: bool) -> None:
        """Append the original absent markers.

        Args:
            playlist: Original destination identity.
            uris: Complete absent marker batch.
            top: Whether insertion starts at the front.
        """
        from spotify_manager.routines.new_year import _post_pending

        await _post_pending(self.sp, playlist, uris, top)

    async def move(self, playlist: str, position: int) -> None:
        """Move one original marker to the front.

        Args:
            playlist: Destination identity.
            position: Observed current marker position.
        """
        from spotify_manager.routines.new_year import _move_position

        await _move_position(self.sp, playlist, position)


@dataclass(frozen=True)
class LegacyAnnualCatalog(LegacyAnnualSpotify):
    """Add the original late-resolved chart ownership observation.

    Args:
        resources: Original mutable destination and annual namespace authority.
    """

    resources: AnnualResources

    async def owned(self) -> tuple[OwnedPlaylist, ...]:
        """Read owned playlists.

        Returns:
            Complete original ownership facts.
        """
        return await self.resources.owned()
