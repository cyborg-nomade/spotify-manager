"""Compatibility seams for original legacy control processing."""

from functools import partial

from spotipy.client import Spotify

from spotify_manager.application import legacy_library_control as workflow
from spotify_manager.domain.legacy_library import first_index
from spotify_manager.domain.legacy_library import last_kept_index
from spotify_manager.infrastructure.legacy_library_records import album as parse_album
from spotify_manager.loaders_savers import save_control_file as save_control_file
from spotify_manager.models.albums import SimplifiedAlbum
from spotify_manager.models.file_items import ControlFileItem
from spotify_manager.processors.total_albums_processor import (
    updated_total_albums_with_results as updated_total_albums_with_results,
)


def get_index_for_first_unevaluated_album(control_file: list[ControlFileItem]) -> int:
    """Select the first empty decision, retaining the original zero fallback.

    Args:
        control_file: Original control entries.

    Returns:
        Original matching index or zero.
    """
    return first_index(workflow.control_results(control_file), "")


def get_unevaluated_albums(
    control_file: list[ControlFileItem],
) -> list[ControlFileItem]:
    """Select the original shared-entry control suffix.

    Args:
        control_file: Original control entries.

    Returns:
        Original suffix, including the all-evaluated zero fallback.
    """
    return workflow.unevaluated(control_file, print)


def get_album_results_from_library(
    sp: Spotify, unevaluated_albums: list[ControlFileItem]
) -> list[ControlFileItem]:
    """Mutate original decisions after each singleton membership read.

    Args:
        sp: Original caller-owned client.
        unevaluated_albums: Original mutable selected entries.

    Returns:
        The same selected list.
    """
    return workflow.evaluate(unevaluated_albums, partial(_contains, sp), print)


def check_album_results(
    sp: Spotify,
    control_file: list[ControlFileItem],
    total_albums_file: list[SimplifiedAlbum],
) -> bool:
    """Retain original evaluation, album-save and control-save order.

    Args:
        sp: Original caller-owned client.
        control_file: Original mutable control authority.
        total_albums_file: Original mutable album authority.

    Returns:
        True after accepted completion.
    """
    return workflow.check(
        control_file,
        total_albums_file,
        get_unevaluated_albums,
        partial(get_album_results_from_library, sp),
        updated_total_albums_with_results,
        save_control_file,
        print,
    )


def get_last_kept_album_item_index(control_file: list[ControlFileItem]) -> int:
    """Select the last keep decision, retaining the original zero fallback.

    Args:
        control_file: Original control entries.

    Returns:
        Original matching index or zero.
    """
    return last_kept_index(workflow.control_results(control_file))


def get_starting_index(
    control_file: list[ControlFileItem], total_album_list: list[SimplifiedAlbum]
) -> int:
    """Select the original one-based continuation after the last kept album.

    Args:
        control_file: Original control entries.
        total_album_list: Original album authority.

    Returns:
        Original continuation index.

    Raises:
        IndexError: Original control authority is empty.
    """
    return workflow.starting_index(control_file, total_album_list, print)


def enrich_album(spotify_id: str, sp: Spotify) -> SimplifiedAlbum:
    """Convert original metadata with first-credit artist semantics.

    Args:
        spotify_id: Original requested identity.
        sp: Original caller-owned client.

    Returns:
        Original simplified album model.
    """
    return parse_album(sp.album(spotify_id))


def _contains(sp: Spotify, identifier: str) -> object:
    return sp.current_user_saved_albums_contains([identifier])[0]
