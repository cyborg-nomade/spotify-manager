"""Existing Spotify, mirror and persistence boundaries for Wine Cellar refill."""

import asyncio
from dataclasses import dataclass
from pathlib import Path

from spotify_manager.application.checkpoints import StateWriter
from spotify_manager.application.library_affinity import library_affinity
from spotify_manager.application.new_wine_values import CellarRefillResult
from spotify_manager.application.ports.listening import RetryCall
from spotify_manager.application.ports.spotify_client import SpotifyClient as Spotify
from spotify_manager.application.wine_cellar import Inventory
from spotify_manager.application.wine_cellar import LibraryCounts
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.catalog import ReleaseTrack
from spotify_manager.infrastructure.async_work import blocking_capacity
from spotify_manager.infrastructure.spotify_async.blocking import finish_blocking
from spotify_manager.routines import new_wine as legacy


@dataclass(frozen=True)
class WineCellarAccess:
    """Retain the original client, mirrors, namespace and audit destination.

    Args:
        client: Caller-owned synchronous Spotify client.
        retry: Existing retry/cancellation policy.
        state_access: Already-resolved namespace adapter.
        log_path: Original audit destination.
        liked_path: Canonical liked-track mirror.
        albums_path: Canonical saved-album mirror.
    """

    client: Spotify
    retry: RetryCall
    state_access: StateWriter
    log_path: Path
    liked_path: Path
    albums_path: Path

    async def playlist(self, playlist_id: str) -> tuple[PlaylistTrack, ...]:
        """Read the original ordered playlist observations.

        Args:
            playlist_id: Source or destination identifier.

        Returns:
            Parsed playable markers.
        """
        from spotify_manager.routines.new_wine import (
            async_load_playlist_tracks as load_playlist_tracks,
        )

        return await load_playlist_tracks(self.client, playlist_id, self.retry)

    async def inventory(self) -> Inventory:
        """Read candidate IDs from the existing canonical mirrors.

        Returns:
            Liked-track and saved-album maps keyed by normalized artist name.
        """
        from spotify_manager.routines.new_wine import _load_no_discovery_inventory

        async with blocking_capacity():
            file_operation = asyncio.create_task(
                asyncio.to_thread(
                    _load_no_discovery_inventory, self.liked_path, self.albums_path
                )
            )
            return await finish_blocking(file_operation)

    async def counts(self, artist: str, inventory: Inventory) -> LibraryCounts:
        """Read live membership under the original early-stop policy.

        Args:
            artist: Source primary artist name.
            inventory: Mirror candidate IDs.

        Returns:
            Liked count, saved-album count and eligibility.
        """
        from spotify_manager.routines.new_wine import _artist_key

        tracks, albums = inventory
        key = _artist_key(artist)
        return await library_affinity(
            ArtistLibraryMembership(self.client, artist, self.retry),
            albums.get(key, ()),
            tracks.get(key, ()),
            batch_size=legacy.LIKED_TRACK_BATCH_SIZE,
            minimum_albums=legacy.NO_DISCOVERY_MIN_SAVED_ALBUMS,
            minimum_tracks=legacy.NO_DISCOVERY_MIN_LIKED_TRACKS,
        )

    async def append(self, playlist_id: str, source: PlaylistTrack) -> None:
        """Append the cellar marker to New Wine.

        Args:
            playlist_id: Destination playlist.
            source: Original cellar marker.
        """
        from spotify_manager.routines.new_wine import _add_playlist_track

        track = ReleaseTrack(source.spotify_id, source.uri, source.name, 1, 1)
        await _add_playlist_track(self.client, playlist_id, track, self.retry)

    async def remove(self, playlist_id: str, source: PlaylistTrack) -> None:
        """Remove the cellar marker after its replacement is secure.

        Args:
            playlist_id: Cellar playlist.
            source: Original marker.
        """
        from spotify_manager.routines.new_wine import _remove_playlist_track

        await _remove_playlist_track(self.client, playlist_id, source, self.retry)

    async def save(self, state: dict[str, object]) -> None:
        """Persist one pending-transfer checkpoint.

        Args:
            state: Complete New Wine namespace.
        """
        await self.state_access.save(state)

    async def audit(self, run_id: str, result: CellarRefillResult) -> None:
        """Append the original refill audit record.

        Args:
            run_id: Original execution identifier.
            result: Accepted or previewed refill outcome.
        """
        from spotify_manager.routines.new_wine import (
            append_cellar_log as _append_cellar_log,
        )

        async with blocking_capacity():
            file_operation = asyncio.create_task(
                asyncio.to_thread(_append_cellar_log, run_id, result, self.log_path)
            )
            await finish_blocking(file_operation)

    def source(self, raw: object) -> PlaylistTrack:
        """Reconstruct a pending marker with unchanged validation.

        Args:
            raw: Serialized source record.

        Returns:
            Original source value.
        """
        from spotify_manager.routines.new_wine import _playlist_track_from_record

        return _playlist_track_from_record(raw)


@dataclass(frozen=True)
class ArtistLibraryMembership:
    """Bind one artist's membership reads to the original SDK helper expressions.

    Args:
        client: Caller-owned Spotify client.
        artist: Original display name used in retry descriptions.
        retry: Existing retry/cancellation callback.
    """

    client: Spotify
    artist: str
    retry: RetryCall

    async def albums(self, ids: list[str]) -> tuple[bool, ...]:
        """Read validated saved-album statuses.

        Args:
            ids: Candidate album IDs in mirror order.

        Returns:
            Boolean statuses in the same order.
        """
        from spotify_manager.routines.new_wine import _affinity_album_statuses

        return await _affinity_album_statuses(self.client, self.artist, ids, self.retry)

    async def tracks(self, ids: list[str]) -> tuple[bool, ...]:
        """Read validated liked-track statuses.

        Args:
            ids: Candidate track IDs in mirror order.

        Returns:
            Boolean statuses in the same order.
        """
        from spotify_manager.routines.new_wine import _affinity_track_statuses

        return await _affinity_track_statuses(self.client, self.artist, ids, self.retry)
