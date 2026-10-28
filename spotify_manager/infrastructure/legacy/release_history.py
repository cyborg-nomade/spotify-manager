"""Retain original New Kids track and liked-status observation boundaries."""

from dataclasses import dataclass

from spotify_manager.application.ports.listening import RetryCall
from spotify_manager.application.ports.spotify_client import SpotifyClient as Spotify
from spotify_manager.domain.discovery import CatalogTrack
from spotify_manager.domain.discovery import RankedRelease


@dataclass(frozen=True)
class LegacyReleaseHistory:
    """Bind the caller-owned SDK and retry policy to historical completion reads.

    Args:
        client: Existing synchronous Spotify client.
        retry: Original retry/cancellation callback.
    """

    client: Spotify
    retry: RetryCall

    async def tracks(self, release: RankedRelease) -> tuple[CatalogTrack, ...]:
        """Read a release at the original catalog boundary.

        Args:
            release: Requested parsed release.

        Returns:
            Original ordered catalog tracks with primary credits.
        """
        from spotify_manager.routines.new_kids import (
            async_load_release_tracks as load_release_tracks,
        )

        return await load_release_tracks(self.client, release, self.retry)

    async def likes(self, ids: list[str], cache: dict[str, bool]) -> None:
        """Populate missing statuses using the existing conservative batch helper.

        Args:
            ids: Original requested sequence, retaining duplicates.
            cache: Shared run-owned memberships, updated in place.
        """
        from spotify_manager.routines.new_wine import (
            async_get_liked_statuses as get_liked_statuses,
        )

        await get_liked_statuses(self.client, ids, cache, self.retry)
