"""Invoke legacy library maintenance through explicitly composed application stages."""

from functools import partial

from spotipy import Spotify

from spotify_manager.application import legacy_library_conversion as workflow
from spotify_manager.application.legacy_library_monthly import count_artists
from spotify_manager.application.legacy_library_monthly import run
from spotify_manager.application.legacy_library_refresh import refresh
from spotify_manager.bootstrap.legacy_library import album_refresh
from spotify_manager.bootstrap.legacy_library import conversion_catalog
from spotify_manager.bootstrap.legacy_library import conversion_files
from spotify_manager.bootstrap.legacy_library import monthly_actions
from spotify_manager.bootstrap.legacy_library import monthly_files
from spotify_manager.infrastructure.legacy_library_errors import LegacyFailure
from spotify_manager.loaders_savers import (
    load_your_library_file as load_your_library_file,
)
from spotify_manager.models.albums import SimplifiedAlbum
from spotify_manager.routines.convert_library_file import _analyse_added
from spotify_manager.routines.convert_library_file import _analyse_removed
from spotify_manager.utils.comparison import (
    compare_and_get_dict as compare_and_get_dict,
)


def run_monthly_routines(sp: Spotify) -> None:
    """Run original monthly stages, retaining legacy false-result handling.

    Args:
        sp: Original caller-owned synchronous client.
    """
    run(monthly_files(), monthly_actions(sp), print)


def compare_your_library_and_all_albums() -> None:
    """Publish the original comparison after export and legacy file reads."""
    workflow.compare(conversion_files(), compare_and_get_dict)


def analyse_comparison(sp: Spotify) -> None:
    """Display original live membership facts for the persisted comparison.

    Args:
        sp: Original caller-owned synchronous client.
    """
    workflow.analyse(
        conversion_files(),
        partial(_analyse_removed, sp),
        partial(_analyse_added, sp),
        print,
    )


def convert_your_library_file(sp: Spotify) -> None:
    """Apply original conversion decisions and publish sorted legacy albums.

    Args:
        sp: Original caller-owned synchronous client.
    """
    workflow.convert(conversion_files(), conversion_catalog(sp), print)


def restore_your_library_from_file(sp: Spotify) -> None:
    """Restore original exported artists before liked tracks.

    Args:
        sp: Original caller-owned synchronous client.
    """
    workflow.restore(conversion_files(), conversion_catalog(sp), print)


def count_artists_in_library() -> int:
    """Read the original export and count every artist entry.

    Returns:
        Original raw artist-list length.
    """
    from spotify_manager.loaders_savers import load_your_library_file

    return count_artists(load_your_library_file)


def update_total_album_list(sp: Spotify, just_update: bool) -> list[SimplifiedAlbum]:
    """Refresh saved albums through the original incremental and failure stages.

    Args:
        sp: Caller-owned synchronous Spotify client.
        just_update: Whether to append from the original stored-album count.

    Returns:
        Published albums or the original partially modified fallback authority.
    """
    return refresh(album_refresh(sp), just_update, print, LegacyFailure)
