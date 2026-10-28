"""Bind Queue planning to original synchronous catalog and assessment seams."""

from dataclasses import dataclass

from spotify_manager.application.ports.spotify_client import SpotifyClient as Spotify
from spotify_manager.domain.discovery import CatalogTrack
from spotify_manager.domain.discovery import RankedRelease
from spotify_manager.routines import the_queue as legacy


@dataclass(frozen=True)
class LegacyQueuePlanning:
    """Retain original caller-owned client, retry and shared assessment behavior.

    Args:
        spotify: Original caller-owned Spotify client.
        retry: Original retry boundary.
    """

    spotify: Spotify
    retry: legacy.RetryCall

    async def top(self, artist: str) -> tuple[CatalogTrack, ...]:
        """Read original ordered top tracks before membership.

        Args:
            artist: Original primary artist identity.

        Returns:
            Original ordered eligible top tracks.
        """
        from spotify_manager.routines.new_kids import (
            async_load_top_track_data as load_top_track_data,
        )

        _, tracks = await load_top_track_data(self.spotify, artist, self.retry)
        return tracks

    async def liked(self, tracks: tuple[CatalogTrack, ...]) -> dict[str, bool]:
        """Retain original top membership validation and retry text.

        Args:
            tracks: Original bounded top-track window.

        Returns:
            Original liked statuses.
        """
        from spotify_manager.routines.the_queue import _liked_statuses

        return await _liked_statuses(self.spotify, tracks, self.retry)

    async def catalog(self, artist: str) -> tuple[RankedRelease, ...]:
        """Read original ranked catalog after top membership.

        Args:
            artist: Original primary artist identity.

        Returns:
            Original ranked releases in source order.
        """
        from spotify_manager.routines.new_kids import (
            async_load_ranked_catalog as load_ranked_catalog,
        )

        return await load_ranked_catalog(self.spotify, artist, self.retry)

    async def tracks(self, release: RankedRelease) -> tuple[CatalogTrack, ...]:
        """Read uncached preferred-release tracks with original paging and retry.

        Args:
            release: Original requested preferred release.

        Returns:
            Original ordered catalog tracks.
        """
        from spotify_manager.routines.new_kids import (
            async_load_release_tracks as load_release_tracks,
        )

        return await load_release_tracks(self.spotify, release, self.retry)
