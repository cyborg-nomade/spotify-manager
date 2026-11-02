"""Named external resources for legacy library maintenance."""

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import cast

from spotify_manager import loaders_savers as files
from spotify_manager.application.legacy_library_effects import Comparison
from spotify_manager.application.legacy_library_effects import ComparisonAlbum
from spotify_manager.application.legacy_library_effects import Page
from spotify_manager.application.ports.spotify_client import SpotifyClient as Spotify
from spotify_manager.application.ports.spotify_client import SpotifyClients
from spotify_manager.infrastructure import legacy_library_records as records
from spotify_manager.infrastructure.async_work import blocking_capacity
from spotify_manager.infrastructure.spotify_async.blocking import finish_blocking
from spotify_manager.infrastructure.spotify_payloads import AlbumCredits
from spotify_manager.models.albums import SimplifiedAlbum
from spotify_manager.models.file_items import ControlFileItem
from spotify_manager.models.stats import StatsFileItem
from spotify_manager.models.tracks import SimplifiedTrack
from spotify_manager.models.your_library import YourLibraryArtist
from spotify_manager.models.your_library import YourLibraryFile
from spotify_manager.models.your_library import YourLibraryTrack


class LegacyLibraryFiles:
    """Read and publish legacy files using their original codecs."""

    async def albums(self) -> list[SimplifiedAlbum]:
        """Legacy total-album read.

        Returns:
            Original boundary result.
        """
        async with blocking_capacity():
            task = asyncio.create_task(asyncio.to_thread(self._blocking_albums))
            return await finish_blocking(task)

    def _blocking_albums(self) -> list[SimplifiedAlbum]:
        """Legacy total-album read.

        Returns:
            Original boundary result.
        """
        return files.load_total_albums_file()

    async def control(self) -> list[ControlFileItem]:
        """Original control read.

        Returns:
            Original boundary result.
        """
        async with blocking_capacity():
            task = asyncio.create_task(asyncio.to_thread(self._blocking_control))
            return await finish_blocking(task)

    def _blocking_control(self) -> list[ControlFileItem]:
        """Original control read.

        Returns:
            Original boundary result.
        """
        return files.load_control_file()

    async def export(self) -> YourLibraryFile:
        """Original export read.

        Returns:
            Original boundary result.
        """
        async with blocking_capacity():
            task = asyncio.create_task(asyncio.to_thread(self._blocking_export))
            return await finish_blocking(task)

    def _blocking_export(self) -> YourLibraryFile:
        """Original export read.

        Returns:
            Original boundary result.
        """
        return files.load_your_library_file()

    async def comparison(self) -> Comparison:
        """Original unchecked comparison read.

        Returns:
            Original boundary result.
        """
        async with blocking_capacity():
            task = asyncio.create_task(asyncio.to_thread(self._blocking_comparison))
            return await finish_blocking(task)

    def _blocking_comparison(self) -> Comparison:
        """Original unchecked comparison read.

        Returns:
            Original boundary result.
        """
        return files.load_comparison_file()

    async def save_albums(self, albums: list[SimplifiedAlbum]) -> None:
        """Original album publication.

        Args:
            albums: Original albums.
        """
        async with blocking_capacity():
            task = asyncio.create_task(
                asyncio.to_thread(self._blocking_save_albums, albums)
            )
            return await finish_blocking(task)

    def _blocking_save_albums(self, albums: list[SimplifiedAlbum]) -> None:
        """Original album publication.

        Args:
            albums: Original albums.
        """
        return files.save_total_albums_file(albums)

    async def save_control(self, control: list[ControlFileItem]) -> None:
        """Original control publication.

        Args:
            control: Original control.
        """
        async with blocking_capacity():
            task = asyncio.create_task(
                asyncio.to_thread(self._blocking_save_control, control)
            )
            return await finish_blocking(task)

    def _blocking_save_control(self, control: list[ControlFileItem]) -> None:
        """Original control publication.

        Args:
            control: Original control.
        """
        return files.save_control_file(control)

    async def save_stats(self, stats: StatsFileItem) -> None:
        """Original statistics publication.

        Args:
            stats: Original stats.
        """
        async with blocking_capacity():
            task = asyncio.create_task(
                asyncio.to_thread(self._blocking_save_stats, stats)
            )
            return await finish_blocking(task)

    def _blocking_save_stats(self, stats: StatsFileItem) -> None:
        """Original statistics publication.

        Args:
            stats: Original stats.
        """
        return files.save_stats_file(stats)

    async def save_comparison(self, comparison: Comparison) -> None:
        """Original comparison publication.

        Args:
            comparison: Original comparison.
        """
        async with blocking_capacity():
            task = asyncio.create_task(
                asyncio.to_thread(self._blocking_save_comparison, comparison)
            )
            return await finish_blocking(task)

    def _blocking_save_comparison(self, comparison: Comparison) -> None:
        """Original comparison publication.

        Args:
            comparison: Original comparison.
        """
        return files.save_comparison_file(comparison)


@dataclass(frozen=True)
class SpotifyConversionCatalog:
    """Bind legacy singleton membership and restoration effects.

    Args:
        spotify: Caller-owned synchronous client.
    """

    spotify: Spotify

    async def contains(self, identifier: str) -> object:
        """Original saved-album singleton query.

        Args:
            identifier: Original identifier.

        Returns:
            Original boundary result.
        """
        from spotify_manager.routines.convert_library_file import _contains_removed

        return await _contains_removed(self.spotify, identifier)

    async def enrich(self, identifier: str) -> SimplifiedAlbum:
        """Original album-model conversion.

        Args:
            identifier: Original identifier.

        Returns:
            Original boundary result.
        """
        from spotify_manager.processors.control_file_processors import (
            async_enrich_album as enrich_album,
        )

        return await enrich_album(identifier, self.spotify)

    async def artist_saved(self, artist: YourLibraryArtist) -> bool:
        """Original artist membership.

        Args:
            artist: Original artist.

        Returns:
            Original boundary result.
        """
        from spotify_manager.processors.your_library_processors import (
            async_is_in_library_artist as is_in_library_artist,
        )

        return await is_in_library_artist(self.spotify, artist)

    async def track_saved(self, track: YourLibraryTrack) -> bool:
        """Original track membership.

        Args:
            track: Original track.

        Returns:
            Original boundary result.
        """
        from spotify_manager.processors.your_library_processors import (
            async_is_in_library_track as is_in_library_track,
        )

        return await is_in_library_track(self.spotify, track)

    async def follow(self, artist: YourLibraryArtist) -> None:
        """Original artist save.

        Args:
            artist: Original artist.
        """
        from spotify_manager.processors.your_library_processors import (
            async_save_to_library_artist as save_to_library_artist,
        )

        return await save_to_library_artist(self.spotify, artist)

    async def like(self, track: YourLibraryTrack) -> None:
        """Original track save.

        Args:
            track: Original track.
        """
        from spotify_manager.processors.your_library_processors import (
            async_save_to_library_track as save_to_library_track,
        )

        return await save_to_library_track(self.spotify, track)

    async def add_contains(self, identifier: str) -> object:
        """Original addition membership seam.

        Args:
            identifier: Original identifier.

        Returns:
            Original boundary result.
        """
        from spotify_manager.routines.convert_library_file import _contains_added

        return await _contains_added(self.spotify, identifier)


@dataclass(frozen=True)
class SpotifyAlbumRefresh:
    """Bind original raw paging, conversion and publication.

    Args:
        spotify: Caller-owned synchronous client.
    """

    spotify: Spotify

    async def saved(self, offset: int) -> Page:
        """Original initial saved-album page.

        Args:
            offset: Original offset.

        Returns:
            Original boundary result.
        """
        from spotify_manager.processors.total_albums_processor import _saved_page

        return await _saved_page(self.spotify, offset)

    async def recover(self, offset: int) -> Page:
        """Original failed-next fallback read.

        Args:
            offset: Original offset.

        Returns:
            Original boundary result.
        """
        from spotify_manager.processors.total_albums_processor import _recover_page

        return await _recover_page(self.spotify, offset)

    async def next(self, page: Page) -> Page:
        """Original next page.

        Args:
            page: Original page.

        Returns:
            Original boundary result.
        """
        from spotify_manager.processors.total_albums_processor import _next_album_page

        return await _next_album_page(self.spotify, page)

    def parse(self, rows: list[object]) -> list[SimplifiedAlbum]:
        """Original saved-album conversion.

        Args:
            rows: Original rows.

        Returns:
            Original boundary result.
        """
        return records.saved_albums(rows)

    async def load(self) -> list[SimplifiedAlbum]:
        """Original incremental authority.

        Returns:
            Original boundary result.
        """
        async with blocking_capacity():
            task = asyncio.create_task(asyncio.to_thread(self._blocking_load))
            return await finish_blocking(task)

    def _blocking_load(self) -> list[SimplifiedAlbum]:
        """Original incremental authority.

        Returns:
            Original boundary result.
        """
        return files.load_total_albums_file()

    async def save(self, albums: list[SimplifiedAlbum]) -> None:
        """Original accepted album publication.

        Args:
            albums: Original albums.
        """
        async with blocking_capacity():
            task = asyncio.create_task(asyncio.to_thread(self._blocking_save, albums))
            return await finish_blocking(task)

    def _blocking_save(self, albums: list[SimplifiedAlbum]) -> None:
        """Original accepted album publication.

        Args:
            albums: Original albums.
        """
        return files.save_total_albums_file(albums)

    def limit(self) -> int:
        """Original live page-size observation.

        Returns:
            Original boundary result.
        """
        from spotify_manager.processors import total_albums_processor as total

        return total.settings.limit


@dataclass(frozen=True)
class SpotifyPlaylistClock:
    """Bind original independent clock observations and creation request.

    Args:
        spotify: Caller-owned synchronous client.
    """

    spotify: Spotify

    def now(self) -> datetime:
        """Original naive local clock.

        Returns:
            Original boundary result.
        """
        from spotify_manager.processors import total_albums_processor as total

        return total.datetime.now()

    async def create(self, name: str) -> object:
        """Original named playlist request.

        Args:
            name: Original name.

        Returns:
            Original boundary result.
        """
        from spotify_manager.processors.total_albums_processor import _create_playlist

        return await _create_playlist(self.spotify, name)


@dataclass(frozen=True)
class SpotifyTrackRead:
    """Bind original raw track paging, coercion, sorting and validation.

    Args:
        spotify: Caller-owned synchronous client.
    """

    spotify: Spotify

    async def read(self, identifier: str) -> Page:
        """Original first album-track page.

        Args:
            identifier: Original identifier.

        Returns:
            Original boundary result.
        """
        from spotify_manager.processors.total_albums_processor import _track_page

        return await _track_page(self.spotify, identifier)

    async def next(self, page: Page) -> Page:
        """Original next track page.

        Args:
            page: Original page.

        Returns:
            Original boundary result.
        """
        from spotify_manager.processors.total_albums_processor import _next_track_page

        return await _next_track_page(self.spotify, page)

    def parse(self, rows: list[object]) -> list[dict[str, object]]:
        """Original truthy row coercion.

        Args:
            rows: Original rows.

        Returns:
            Original boundary result.
        """
        return records.track_rows(rows)

    def sort(self, rows: list[dict[str, object]]) -> list[dict[str, object]]:
        """Original stable disc/track sort.

        Args:
            rows: Original rows.

        Returns:
            Original boundary result.
        """
        return records.sort_tracks(rows)

    def validate(self, rows: list[dict[str, object]]) -> list[SimplifiedTrack]:
        """Original final model validation.

        Args:
            rows: Original rows.

        Returns:
            Original boundary result.
        """
        return records.validate_tracks(rows)


@dataclass(frozen=True)
class SpotifyControlMembership:
    """Read singleton saved-album control facts.

    Args:
        spotify: Caller-owned synchronous client.
    """

    spotify: Spotify

    async def contains(self, identifier: str) -> object:
        """Read membership.

        Args:
            identifier: Album identity.

        Returns:
            Original permissive status.
        """
        from spotify_manager.processors.control_file_processors import _contains

        return await _contains(self.spotify, identifier)


class LegacyMonthlyLimits:
    """Observe live legacy settings at the original selection boundary."""

    def count(self) -> int:
        """Observe the monthly slice size.

        Returns:
            Configured album count.
        """
        from spotify_manager.processors import total_albums_processor as total

        return total.settings.albums_to_add


@dataclass(frozen=True)
class SpotifyPlaylistWrites:
    """Accept playlist additions through the original small/batch seams.

    Args:
        spotify: Caller-owned synchronous client.
    """

    spotify: Spotify

    async def single(self, identifier: str, uris: list[str]) -> None:
        """Accept a small addition.

        Args:
            identifier: Destination playlist.
            uris: Ordered tracks.
        """
        from spotify_manager.processors.total_albums_processor import _append_single

        await _append_single(self.spotify, identifier, uris)

    async def batch(self, identifier: str, uris: list[str]) -> None:
        """Accept a batch addition.

        Args:
            identifier: Destination playlist.
            uris: Ordered tracks.
        """
        from spotify_manager.processors.total_albums_processor import _append_batch

        await _append_batch(self.spotify, identifier, uris)


class LegacyComparisonMetadata:
    """Read comparison metadata using the original per-identity client scope."""

    def enrich(self, identifier: str) -> ComparisonAlbum:
        """Read and present metadata.

        Args:
            identifier: Album identity.

        Returns:
            Original comparison metadata.
        """
        from spotify_manager.utils.comparison import enrich_id_to_album_dict

        return enrich_id_to_album_dict(identifier)


@dataclass(frozen=True)
class NativeComparisonMetadata:
    """Read per-identity metadata with invocation-owned native client scopes.

    Args:
        clients: Original independent client scope provider.
    """

    clients: SpotifyClients

    async def enrich(self, identifier: str) -> ComparisonAlbum:
        """Retain requested identity, first-credit selection and display order.

        Args:
            identifier: Original requested album identity.

        Returns:
            Original unchecked comparison metadata.
        """
        print(identifier)
        spotify = await self.clients.client()
        album = cast(AlbumCredits, await spotify.album(identifier))
        print(album["name"])
        return cast(
            ComparisonAlbum,
            {
                "name": album["name"],
                "artist": album["artists"][0]["name"],
                "id": identifier,
            },
        )


@dataclass(frozen=True)
class AsyncComparisonMetadata:
    """Adapt the original synchronous Python metadata hook at its outer I/O edge.

    Args:
        source: Original SDK-constructing compatibility resource.
    """

    source: LegacyComparisonMetadata

    async def enrich(self, identifier: str) -> ComparisonAlbum:
        """Await the existing complete metadata observation.

        Args:
            identifier: Original requested album identity.

        Returns:
            Original unchecked comparison metadata.
        """
        async with blocking_capacity():
            task = asyncio.create_task(
                asyncio.to_thread(self.source.enrich, identifier)
            )
            return await finish_blocking(task)


@dataclass(frozen=True)
class SpotifyComparisonMembership:
    """Observe analysis membership through its original transport seams.

    Args:
        spotify: Caller-owned synchronous client.
    """

    spotify: Spotify

    async def contains(self, identifier: str) -> object:
        """Read removal membership.

        Args:
            identifier: Album identity.

        Returns:
            Original status.
        """
        from spotify_manager.routines.convert_library_file import _analyse_removed

        return await _analyse_removed(self.spotify, identifier)

    async def add_contains(self, identifier: str) -> object:
        """Read addition membership.

        Args:
            identifier: Album identity.

        Returns:
            Original status.
        """
        from spotify_manager.routines.convert_library_file import _analyse_added

        return await _analyse_added(self.spotify, identifier)
