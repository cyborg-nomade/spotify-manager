"""Compatibility seams for original album refresh and monthly playlists."""

from datetime import datetime
from functools import partial
from typing import cast

from spotipy.client import Spotify

from spotify_manager.application import legacy_library_control as control
from spotify_manager.application import legacy_library_refresh as workflow
from spotify_manager.application.legacy_library_effects import Page
from spotify_manager.application.legacy_library_effects import PlaylistClock
from spotify_manager.bootstrap import legacy_library as composition
from spotify_manager.domain.legacy_library import first_index
from spotify_manager.domain.legacy_library import monthly_slice
from spotify_manager.infrastructure.legacy_library_errors import LegacyFailure
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


def update_total_album_list(sp: Spotify, just_update: bool) -> list[SimplifiedAlbum]:
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

    return operation(sp, just_update)


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


def create_playlist(sp: Spotify) -> str:
    """Create the original monthly playlist with independent clock reads.

    Args:
        sp: Original caller-owned client.

    Returns:
        Original accepted playlist identity.
    """
    return workflow.playlist(
        PlaylistClock(datetime.now, partial(_create_playlist, sp)), print
    )


def get_ordered_tracks(sp: Spotify, album: SimplifiedAlbum) -> list[SimplifiedTrack]:
    """Collect original track pages and sort stably by disc and track number.

    Args:
        sp: Original caller-owned client.
        album: Original selected album.

    Returns:
        Original ordered simplified tracks.
    """
    return workflow.tracks(composition.track_read(sp), album, print)


def append_to_playlist(
    sp: Spotify, ordered_tracks: list[SimplifiedTrack], playlist_id: str
) -> None:
    """Append original track batches, retaining one request for empty input.

    Args:
        sp: Original caller-owned client.
        ordered_tracks: Original playback order.
        playlist_id: Original destination identity.
    """
    workflow.append_tracks(
        ordered_tracks,
        playlist_id,
        partial(_append_single, sp),
        partial(_append_batch, sp),
        print,
    )


def add_monthly_albums(
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
    return workflow.add_monthly(
        composition.monthly_playlist(sp),
        control_file,
        total_album_list,
        starting_index,
        print,
        LegacyFailure,
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


def updated_total_albums_with_results(
    total_albums_file: list[SimplifiedAlbum], unevaluated_albums: list[ControlFileItem]
) -> None:
    """Apply original rejected-album removals before sorted publication.

    Args:
        total_albums_file: Original mutable album authority.
        unevaluated_albums: Original observed decisions.
    """
    control.reconcile(total_albums_file, unevaluated_albums, save_total_albums_file)


def _saved_page(sp: Spotify, offset: int) -> Page:
    return cast(Page, sp.current_user_saved_albums(limit=settings.limit, offset=offset))


def _recover_page(sp: Spotify, offset: int) -> Page:
    return cast(Page, sp.current_user_saved_albums(limit=settings.limit, offset=offset))


def _next_album_page(sp: Spotify, page: Page) -> Page:
    return cast(Page, sp.next(page))


def _create_playlist(sp: Spotify, name: str) -> object:
    return sp.user_playlist_create("12161013970", name=name)


def _track_page(sp: Spotify, identifier: str) -> Page:
    return cast(Page, sp.album_tracks(identifier))


def _next_track_page(sp: Spotify, page: Page) -> Page:
    return cast(Page, sp.next(page))


def _append_single(sp: Spotify, playlist_id: str, uris: list[str]) -> None:
    sp.playlist_add_items(playlist_id, uris)


def _append_batch(sp: Spotify, playlist_id: str, uris: list[str]) -> None:
    sp.playlist_add_items(playlist_id, uris)
