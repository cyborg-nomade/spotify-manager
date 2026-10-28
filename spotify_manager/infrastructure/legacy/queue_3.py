"""Bind Queue 3 playlist and audit effects to the existing compatibility helpers."""

import asyncio
from dataclasses import dataclass
from pathlib import Path

from spotify_manager.application.ports.listening import RetryCall
from spotify_manager.application.ports.spotify_client import SpotifyClient as Spotify
from spotify_manager.application.queue_3_values import Queue3Error
from spotify_manager.domain.catalog import DiscographyRelease
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.catalog import ReleaseTrack
from spotify_manager.infrastructure.async_work import blocking_capacity
from spotify_manager.infrastructure.spotify_async.blocking import finish_blocking
from spotify_manager.routines import new_wine


@dataclass(frozen=True)
class LegacyAnnualImport:
    """Retain Spotify retries, error translation, batching and audit storage.

    Args:
        client: Caller-owned Spotify client.
        retry: Existing request retry and cancellation boundary.
        log_path: Original audit destination.
    """

    client: Spotify
    retry: RetryCall
    log_path: Path

    async def read(self, playlist_id: str) -> tuple[PlaylistTrack, ...]:
        """Read source markers and translate the original playlist error.

        Args:
            playlist_id: Previous-year discovery playlist identifier.

        Returns:
            Parsed markers in source order.

        Raises:
            Queue3Error: The existing playlist reader fails.
        """
        from spotify_manager.routines.new_wine import (
            async_load_playlist_tracks as load_playlist_tracks,
        )

        try:
            return await load_playlist_tracks(self.client, playlist_id, self.retry)
        except new_wine.NewWineError as exc:
            raise Queue3Error(str(exc)) from exc

    async def append(
        self, playlist_id: str, tracks: list[PlaylistTrack], description: str
    ) -> None:
        """Append markers through the original ordered batch helper.

        Args:
            playlist_id: Destination Queue 3 identifier.
            tracks: Selected artist markers in source order.
            description: Original retry description before batch suffixes.
        """
        from spotify_manager.routines.queue_3 import _add_playlist_tracks

        await _add_playlist_tracks(
            self.client, playlist_id, tracks, self.retry, description
        )

    async def audit(self, event: str, details: dict[str, object]) -> None:
        """Persist original audit fields at the caller's audit destination.

        Args:
            event: Original event identifier.
            details: Original structured event fields.
        """
        from spotify_manager.routines.queue_3 import append_event as _append_event

        async with blocking_capacity():
            file_operation = asyncio.create_task(
                asyncio.to_thread(_append_event, self.log_path, event, **details)
            )
            await finish_blocking(file_operation)

    async def remove(self, playlist_id: str, uris: list[str], description: str) -> None:
        """Remove markers through original URI deduplication and ordered batches.

        Args:
            playlist_id: Queue 3 destination.
            uris: Original marker URI selection.
            description: Original retry message before batch suffixes.
        """
        from spotify_manager.routines.queue_3 import _remove_playlist_uris

        await _remove_playlist_uris(
            self.client, playlist_id, uris, self.retry, description
        )


@dataclass(frozen=True)
class LegacyQueue3Catalog:
    """Read chronological tracks and live memberships through existing adapters.

    Args:
        client: Caller-owned Spotify client.
        retry: Existing request retry and cancellation boundary.
        liked: Caller-owned live membership cache for the current run.
    """

    client: Spotify
    retry: RetryCall
    liked: dict[str, bool]

    async def discography(self, artist_id: str) -> tuple[DiscographyRelease, ...]:
        """Read chronological eligible editions through the original catalog loader.

        Args:
            artist_id: Original logical artist identifier.

        Returns:
            Selected studio releases in original chronological order.
        """
        from spotify_manager.routines.slow_listening import (
            async_load_discography as load_discography,
        )

        return await load_discography(self.client, artist_id, self.retry)

    async def tracks(self, release: DiscographyRelease) -> tuple[ReleaseTrack, ...]:
        """Read a selected edition through the original ordered-track loader.

        Args:
            release: Preferred studio edition.

        Returns:
            Original playable tracks in disc and track order.
        """
        from spotify_manager.routines.slow_listening import (
            async_load_release_tracks as load_release_tracks,
        )

        return await load_release_tracks(self.client, release, self.retry)

    async def memberships(
        self, release: DiscographyRelease, tracks: tuple[ReleaseTrack, ...]
    ) -> dict[str, bool]:
        """Observe live liked statuses for a completed edition.

        Args:
            release: Completed preferred edition.
            tracks: Previously observed complete ordered track list.

        Returns:
            Original run-scoped liked statuses, without applying retention policy.
        """
        from spotify_manager.routines.new_wine import (
            async_get_liked_statuses as get_liked_statuses,
        )

        await get_liked_statuses(
            self.client,
            [track.spotify_id for track in tracks],
            self.liked,
            self.retry,
        )
        return self.liked

    async def release_tracks(
        self, release: DiscographyRelease
    ) -> tuple[ReleaseTrack, ...]:
        """Read the selected edition through the original catalog boundary.

        Args:
            release: Preferred studio edition.

        Returns:
            Original playable tracks in disc and track order.
        """
        return await self.tracks(release)
