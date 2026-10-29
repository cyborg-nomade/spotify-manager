"""Compatibility seams for original legacy control processing."""

import asyncio

from spotipy import Spotify as LegacySpotify
from spotipy.client import Spotify

from spotify_manager.application import legacy_library_control as workflow
from spotify_manager.domain.legacy_library import first_index
from spotify_manager.domain.legacy_library import last_kept_index
from spotify_manager.infrastructure.async_work import blocking_capacity
from spotify_manager.infrastructure.legacy_library_records import album as parse_album
from spotify_manager.infrastructure.legacy_library_resources import (
    SpotifyControlMembership,
)
from spotify_manager.infrastructure.output import STANDARD_OUTPUT
from spotify_manager.infrastructure.spotify_async.blocking import finish_blocking
from spotify_manager.loaders_savers import save_control_file as save_control_file
from spotify_manager.models.albums import SimplifiedAlbum
from spotify_manager.models.file_items import ControlFileItem
from spotify_manager.processors.total_albums_processor import (
    async_updated_total_albums_with_results as updated_total_albums_with_results,
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
    return workflow.unevaluated(control_file, STANDARD_OUTPUT)


async def async_get_album_results_from_library(
    sp: Spotify, unevaluated_albums: list[ControlFileItem]
) -> list[ControlFileItem]:
    """Mutate original decisions after each singleton membership read.

    Args:
        sp: Original caller-owned client.
        unevaluated_albums: Original mutable selected entries.

    Returns:
        The same selected list.
    """
    return await workflow.evaluate(
        unevaluated_albums, SpotifyControlMembership(sp), STANDARD_OUTPUT
    )


async def async_check_album_results(
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
    print("Checking album results...")
    selected = get_unevaluated_albums(control_file)
    await async_get_album_results_from_library(sp, selected)
    await updated_total_albums_with_results(total_albums_file, selected)
    async with blocking_capacity():
        control_write = asyncio.create_task(
            asyncio.to_thread(save_control_file, control_file)
        )
        await finish_blocking(control_write)
    print("Results checked!")
    return True


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
    return workflow.starting_index(control_file, total_album_list, STANDARD_OUTPUT)


async def async_enrich_album(spotify_id: str, sp: Spotify) -> SimplifiedAlbum:
    """Convert original metadata with first-credit artist semantics.

    Args:
        spotify_id: Original requested identity.
        sp: Original caller-owned client.

    Returns:
        Original simplified album model.
    """
    return parse_album(await sp.album(spotify_id))


async def _contains(sp: Spotify, identifier: str) -> object:
    return (await sp.current_user_saved_albums_contains([identifier]))[0]


def get_album_results_from_library(
    sp: LegacySpotify, unevaluated_albums: list[ControlFileItem]
) -> list[ControlFileItem]:
    """Mutate original decisions after each singleton membership read.

    Args:
        sp: Original caller-owned client.
        unevaluated_albums: Original mutable selected entries.

    Returns:
        The same selected list.
    """
    from spotify_manager.bootstrap.execution import run_python
    from spotify_manager.infrastructure.spotify_compat import legacy_spotify

    return run_python(
        async_get_album_results_from_library(legacy_spotify(sp), unevaluated_albums)
    )


def check_album_results(
    sp: LegacySpotify,
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
    from spotify_manager.bootstrap.execution import run_python
    from spotify_manager.infrastructure.spotify_compat import legacy_spotify

    return run_python(
        async_check_album_results(legacy_spotify(sp), control_file, total_albums_file)
    )


def enrich_album(spotify_id: str, sp: LegacySpotify) -> SimplifiedAlbum:
    """Convert original metadata with first-credit artist semantics.

    Args:
        spotify_id: Original requested identity.
        sp: Original caller-owned client.

    Returns:
        Original simplified album model.
    """
    from spotify_manager.bootstrap.execution import run_python
    from spotify_manager.infrastructure.spotify_compat import legacy_spotify

    return run_python(async_enrich_album(spotify_id, legacy_spotify(sp)))
