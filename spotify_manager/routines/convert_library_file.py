"""Stable public entry points for legacy export comparison and conversion."""

from typing import cast

from spotipy import Spotify as LegacySpotify

from spotify_manager.application.ports.spotify_client import SpotifyClient as Spotify
from spotify_manager.loaders_savers import load_comparison_file as load_comparison_file
from spotify_manager.loaders_savers import (
    load_total_albums_file as load_total_albums_file,
)
from spotify_manager.loaders_savers import (
    load_your_library_file as load_your_library_file,
)
from spotify_manager.loaders_savers import save_comparison_file as save_comparison_file
from spotify_manager.loaders_savers import (
    save_total_albums_file as save_total_albums_file,
)
from spotify_manager.processors.total_albums_processor import (
    get_album_index_in_total_albums as get_album_index_in_total_albums,
)
from spotify_manager.utils.comparison import (
    compare_and_get_dict as compare_and_get_dict,
)
from spotify_manager.utils.comparison import (
    get_album_id_list_from_total_albums_file as _total_ids,
)
from spotify_manager.utils.comparison import (
    get_album_id_list_from_your_library_file as _export_ids,
)


get_album_id_list_from_total_albums_file = _total_ids

get_album_id_list_from_your_library_file = _export_ids


async def async_compare_your_library_and_all_albums() -> None:
    """Publish the original comparison after export and legacy file reads."""
    from spotify_manager.interfaces.operations.legacy_library import (
        compare_your_library_and_all_albums as operation,
    )

    return await operation()


async def async_analyse_comparison(sp: Spotify) -> None:
    """Display original live membership facts for the persisted comparison.

    Args:
        sp: Original caller-owned synchronous client.
    """
    from spotify_manager.interfaces.operations.legacy_library import (
        analyse_comparison as operation,
    )

    return await operation(sp)


async def async_convert_your_library_file(sp: Spotify) -> None:
    """Apply original conversion decisions and publish sorted legacy albums.

    Args:
        sp: Original caller-owned synchronous client.
    """
    from spotify_manager.interfaces.operations.legacy_library import (
        convert_your_library_file as operation,
    )

    return await operation(sp)


async def async_restore_your_library_from_file(sp: Spotify) -> None:
    """Restore original exported artists before liked tracks.

    Args:
        sp: Original caller-owned synchronous client.
    """
    from spotify_manager.interfaces.operations.legacy_library import (
        restore_your_library_from_file as operation,
    )

    return await operation(sp)


async def _analyse_removed(sp: Spotify, identifier: str) -> object:
    response = await sp.current_user_saved_albums_contains([identifier])
    return cast(list[bool], response)[0]


async def _analyse_added(sp: Spotify, identifier: str) -> object:
    response = await sp.current_user_saved_albums_contains([identifier])
    return cast(list[bool], response)[0]


async def _contains_removed(sp: Spotify, identifier: str) -> object:
    response = await sp.current_user_saved_albums_contains([identifier])
    return cast(list[bool], response)[0]


async def _contains_added(sp: Spotify, identifier: str) -> object:
    response = await sp.current_user_saved_albums_contains([identifier])
    return cast(list[bool], response)[0]


def compare_your_library_and_all_albums() -> None:
    """Publish the original comparison after export and legacy file reads."""
    from spotify_manager.bootstrap.execution import run_python

    return run_python(async_compare_your_library_and_all_albums())


def analyse_comparison(sp: LegacySpotify) -> None:
    """Display original live membership facts for the persisted comparison.

    Args:
        sp: Original caller-owned synchronous client.
    """
    from spotify_manager.bootstrap.execution import run_python
    from spotify_manager.infrastructure.spotify_compat import legacy_spotify

    return run_python(async_analyse_comparison(legacy_spotify(sp)))


def convert_your_library_file(sp: LegacySpotify) -> None:
    """Apply original conversion decisions and publish sorted legacy albums.

    Args:
        sp: Original caller-owned synchronous client.
    """
    from spotify_manager.bootstrap.execution import run_python
    from spotify_manager.infrastructure.spotify_compat import legacy_spotify

    return run_python(async_convert_your_library_file(legacy_spotify(sp)))


def restore_your_library_from_file(sp: LegacySpotify) -> None:
    """Restore original exported artists before liked tracks.

    Args:
        sp: Original caller-owned synchronous client.
    """
    from spotify_manager.bootstrap.execution import run_python
    from spotify_manager.infrastructure.spotify_compat import legacy_spotify

    return run_python(async_restore_your_library_from_file(legacy_spotify(sp)))
