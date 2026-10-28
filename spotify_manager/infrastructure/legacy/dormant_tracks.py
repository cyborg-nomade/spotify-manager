"""Concrete synchronous catalog reads for dormant-artist track decisions."""

from dataclasses import dataclass

from spotify_manager.application.ports.listening import RetryCall
from spotify_manager.application.ports.spotify_client import SpotifyClient as Spotify
from spotify_manager.domain.discovery import CatalogTrack


@dataclass(frozen=True)
class LegacyDormantCatalog:
    """Own original dormant catalog requests and retry behavior.

    Args:
        spotify: Caller-owned Spotify client.
        retry: Original retry and cancellation boundary.
    """

    spotify: Spotify
    retry: RetryCall

    async def top(self, artist_id: str) -> tuple[CatalogTrack, ...]:
        """Observe the original eligible top tracks.

        Args:
            artist_id: Original mapped artist identity.

        Returns:
            Original ordered top tracks.
        """
        from spotify_manager.routines.new_kids import (
            async_load_top_track_data as load_top_track_data,
        )

        _, tracks = await load_top_track_data(self.spotify, artist_id, self.retry)
        return tracks

    async def liked(self, tracks: tuple[CatalogTrack, ...]) -> dict[str, bool]:
        """Observe the original checked live liked statuses.

        Args:
            tracks: Original ordered marker candidates.

        Returns:
            Original accepted memberships by identity.
        """
        from spotify_manager.routines.blast_from_past_artists import _liked_statuses

        return await _liked_statuses(self.spotify, tracks, self.retry)

    async def tracks(self, artist_id: str) -> tuple[CatalogTrack, ...]:
        """Read the original complete primary-credit catalog.

        Args:
            artist_id: Original mapped artist identity.

        Returns:
            Original complete playable catalog markers.
        """
        from spotify_manager.routines.blast_from_past_artists import _catalog_tracks

        return await _catalog_tracks(self.spotify, artist_id, self.retry)

    async def populate(
        self, tracks: tuple[CatalogTrack, ...]
    ) -> tuple[CatalogTrack, ...]:
        """Observe live popularity only for the original liked fallback markers.

        Args:
            tracks: Original filtered liked catalog markers.

        Returns:
            Original markers with accepted live popularity.
        """
        from spotify_manager.routines.blast_from_past_artists import _track_popularities

        return await _track_popularities(self.spotify, tracks, self.retry)
