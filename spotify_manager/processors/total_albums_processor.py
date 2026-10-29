"""Compatibility seams for original album refresh and monthly playlists."""

import asyncio
from datetime import datetime as datetime
from typing import cast

from spotipy import Spotify as LegacySpotify
from spotipy.client import Spotify

from spotify_manager.application import legacy_library_control as control
from spotify_manager.application import legacy_library_refresh as workflow
from spotify_manager.application.legacy_library_effects import Page
from spotify_manager.bootstrap import legacy_library as composition
from spotify_manager.domain.legacy_library import first_index
from spotify_manager.domain.legacy_library import monthly_slice
from spotify_manager.infrastructure.async_work import blocking_capacity
from spotify_manager.infrastructure.legacy_library_resources import LegacyLibraryFiles
from spotify_manager.infrastructure.legacy_library_resources import SpotifyPlaylistClock
from spotify_manager.infrastructure.legacy_library_resources import (
    SpotifyPlaylistWrites,
)
from spotify_manager.infrastructure.output import STANDARD_OUTPUT
from spotify_manager.infrastructure.spotify_async.blocking import finish_blocking
from spotify_manager.loaders_savers import (
    load_total_albums_file as load_total_albums_file,
)
from spotify_manager.loaders_savers import save_control_file as save_control_file
from spotify_manager.loaders_savers import (
    save_total_albums_file as save_total_albums_file,
)
from spotify_manager.models.albums import SimplifiedAlbum
from spotify_manager.models.file_items import ControlFileItem
from spotify_manager.models.tracks import SimplifiedTrack


settings = composition.legacy_settings()


async def async_update_total_album_list(
    sp: Spotify, just_update: bool
) -> list[SimplifiedAlbum]:
    """Retain original incremental authority, raw paging and failure fallback.

    Args:
        sp: Original caller-owned client.
        just_update: Original incremental flag.

    Returns:
        Published models or the original partially modified fallback authority.
    """
    from spotify_manager.interfaces.operations.legacy_library import (
        update_total_album_list as operation,
    )

    return await operation(sp, just_update)


def get_months_items(
    all_albums: list[SimplifiedAlbum], initial_index: int
) -> list[SimplifiedAlbum]:
    """Select the original permissive monthly slice.

    Args:
        all_albums: Original ordered album authority.
        initial_index: Original unvalidated start index.

    Returns:
        Original selected slice.
    """
    return monthly_slice(all_albums, initial_index, settings.albums_to_add)


async def async_create_playlist(sp: Spotify) -> str:
    """Create the original monthly playlist with independent clock reads.

    Args:
        sp: Original caller-owned client.

    Returns:
        Original accepted playlist identity.
    """
    return await workflow.playlist(SpotifyPlaylistClock(sp), STANDARD_OUTPUT)


async def async_get_ordered_tracks(
    sp: Spotify, album: SimplifiedAlbum
) -> list[SimplifiedTrack]:
    """Collect original track pages and sort stably by disc and track number.

    Args:
        sp: Original caller-owned client.
        album: Original selected album.

    Returns:
        Original ordered simplified tracks.
    """
    return await workflow.tracks(composition.track_read(sp), album, STANDARD_OUTPUT)


async def async_append_to_playlist(
    sp: Spotify, ordered_tracks: list[SimplifiedTrack], playlist_id: str
) -> None:
    """Append original track batches, retaining one request for empty input.

    Args:
        sp: Original caller-owned client.
        ordered_tracks: Original playback order.
        playlist_id: Original destination identity.
    """
    await workflow.append_tracks(
        ordered_tracks,
        playlist_id,
        SpotifyPlaylistWrites(sp),
        STANDARD_OUTPUT,
    )


async def async_add_monthly_albums(
    sp: Spotify,
    control_file: list[ControlFileItem],
    total_album_list: list[SimplifiedAlbum],
    starting_index: int,
) -> bool:
    """Retain original ordered additions and partial acceptance on failure.

    Args:
        sp: Original caller-owned client.
        control_file: Original mutable control authority.
        total_album_list: Original album authority.
        starting_index: Original slice start.

    Returns:
        Whether the complete original sequence succeeded.
    """
    return await workflow.add_monthly(
        composition.monthly_playlist(sp),
        control_file,
        total_album_list,
        starting_index,
        STANDARD_OUTPUT,
    )


def get_album_index_in_total_albums(
    spotify_id: str, total_albums_file: list[SimplifiedAlbum]
) -> int:
    """Find the first album identity with the original zero fallback.

    Args:
        spotify_id: Original requested identity.
        total_albums_file: Original ordered album authority.

    Returns:
        Original first matching index or zero.
    """
    return first_index(control.album_ids(total_albums_file), spotify_id)


async def async_updated_total_albums_with_results(
    total_albums_file: list[SimplifiedAlbum], unevaluated_albums: list[ControlFileItem]
) -> None:
    """Apply original rejected-album removals before sorted publication.

    Args:
        total_albums_file: Original mutable album authority.
        unevaluated_albums: Original observed decisions.
    """
    await control.reconcile(
        total_albums_file, unevaluated_albums, _CompatibilityFiles()
    )


async def _saved_page(sp: Spotify, offset: int) -> Page:
    return cast(
        Page, (await sp.current_user_saved_albums(limit=settings.limit, offset=offset))
    )


async def _recover_page(sp: Spotify, offset: int) -> Page:
    return cast(
        Page, (await sp.current_user_saved_albums(limit=settings.limit, offset=offset))
    )


async def _next_album_page(sp: Spotify, page: Page) -> Page:
    return cast(Page, (await sp.next(page)))


async def _create_playlist(sp: Spotify, name: str) -> object:
    return await sp.user_playlist_create("12161013970", name=name)


async def _track_page(sp: Spotify, identifier: str) -> Page:
    return cast(Page, (await sp.album_tracks(identifier)))


async def _next_track_page(sp: Spotify, page: Page) -> Page:
    return cast(Page, (await sp.next(page)))


async def _append_single(sp: Spotify, playlist_id: str, uris: list[str]) -> None:
    await sp.playlist_add_items(playlist_id, uris)


async def _append_batch(sp: Spotify, playlist_id: str, uris: list[str]) -> None:
    await sp.playlist_add_items(playlist_id, uris)


class _CompatibilityFiles(LegacyLibraryFiles):
    """Retain the public processor's original album publication seam."""

    async def save_albums(self, albums: list[SimplifiedAlbum]) -> None:
        """Publish reconciled albums.

        Args:
            albums: Complete ordered authority.
        """
        async with blocking_capacity():
            task = asyncio.create_task(
                asyncio.to_thread(self._blocking_save_albums, albums)
            )
            return await finish_blocking(task)

    def _blocking_save_albums(self, albums: list[SimplifiedAlbum]) -> None:
        """Publish reconciled albums.

        Args:
            albums: Complete ordered authority.
        """
        save_total_albums_file(albums)


def update_total_album_list(
    sp: LegacySpotify, just_update: bool
) -> list[SimplifiedAlbum]:
    """Retain original incremental authority, raw paging and failure fallback.

    Args:
        sp: Original caller-owned client.
        just_update: Original incremental flag.

    Returns:
        Published models or the original partially modified fallback authority.
    """
    from spotify_manager.bootstrap.execution import run_python
    from spotify_manager.infrastructure.spotify_compat import legacy_spotify

    return run_python(async_update_total_album_list(legacy_spotify(sp), just_update))


def create_playlist(sp: LegacySpotify) -> str:
    """Create the original monthly playlist with independent clock reads.

    Args:
        sp: Original caller-owned client.

    Returns:
        Original accepted playlist identity.
    """
    from spotify_manager.bootstrap.execution import run_python
    from spotify_manager.infrastructure.spotify_compat import legacy_spotify

    return run_python(async_create_playlist(legacy_spotify(sp)))


def get_ordered_tracks(
    sp: LegacySpotify, album: SimplifiedAlbum
) -> list[SimplifiedTrack]:
    """Collect original track pages and sort stably by disc and track number.

    Args:
        sp: Original caller-owned client.
        album: Original selected album.

    Returns:
        Original ordered simplified tracks.
    """
    from spotify_manager.bootstrap.execution import run_python
    from spotify_manager.infrastructure.spotify_compat import legacy_spotify

    return run_python(async_get_ordered_tracks(legacy_spotify(sp), album))


def append_to_playlist(
    sp: LegacySpotify, ordered_tracks: list[SimplifiedTrack], playlist_id: str
) -> None:
    """Append original track batches, retaining one request for empty input.

    Args:
        sp: Original caller-owned client.
        ordered_tracks: Original playback order.
        playlist_id: Original destination identity.
    """
    from spotify_manager.bootstrap.execution import run_python
    from spotify_manager.infrastructure.spotify_compat import legacy_spotify

    return run_python(
        async_append_to_playlist(legacy_spotify(sp), ordered_tracks, playlist_id)
    )


def add_monthly_albums(
    sp: LegacySpotify,
    control_file: list[ControlFileItem],
    total_album_list: list[SimplifiedAlbum],
    starting_index: int,
) -> bool:
    """Retain original ordered additions and partial acceptance on failure.

    Args:
        sp: Original caller-owned client.
        control_file: Original mutable control authority.
        total_album_list: Original album authority.
        starting_index: Original slice start.

    Returns:
        Whether the complete original sequence succeeded.
    """
    from spotify_manager.bootstrap.execution import run_python
    from spotify_manager.infrastructure.spotify_compat import legacy_spotify

    return run_python(
        async_add_monthly_albums(
            legacy_spotify(sp), control_file, total_album_list, starting_index
        )
    )


def updated_total_albums_with_results(
    total_albums_file: list[SimplifiedAlbum], unevaluated_albums: list[ControlFileItem]
) -> None:
    """Apply original rejected-album removals before sorted publication.

    Args:
        total_albums_file: Original mutable album authority.
        unevaluated_albums: Original observed decisions.
    """
    from spotify_manager.bootstrap.execution import run_python

    return run_python(
        async_updated_total_albums_with_results(total_albums_file, unevaluated_albums)
    )
