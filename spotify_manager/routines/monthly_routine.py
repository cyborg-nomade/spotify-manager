"""Stable entry point for the original ordered monthly routine."""

from spotipy.client import Spotify

from spotify_manager.application.legacy_library_monthly import run
from spotify_manager.bootstrap.legacy_library import monthly_actions
from spotify_manager.bootstrap.legacy_library import monthly_files
from spotify_manager.loaders_savers import load_control_file as load_control_file
from spotify_manager.loaders_savers import (
    load_total_albums_file as load_total_albums_file,
)
from spotify_manager.processors.control_file_processors import (
    check_album_results as check_album_results,
)
from spotify_manager.processors.control_file_processors import (
    get_starting_index as get_starting_index,
)
from spotify_manager.processors.stats_processors import update_stats as update_stats
from spotify_manager.processors.total_albums_processor import (
    add_monthly_albums as add_monthly_albums,
)


def run_monthly_routines(sp: Spotify) -> None:
    """Run original monthly stages, retaining legacy false-result handling.

    Args:
        sp: Original caller-owned synchronous client.
    """
    run(monthly_files(), monthly_actions(sp), print)
